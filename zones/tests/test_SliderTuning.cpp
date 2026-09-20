// Tuning blob validation, NVS discipline, live TUNE/RAW commands and hysteresis.
#include "zone_stubs.h"
#include "../firmware/PoolZone/PoolZone.ino"
#include "sketch_test.h"

static bool savedTuning() { return Preferences::blobs.count("pool-slider/tune-v1") != 0; }
static std::vector<uint8_t> savedTicks() { return Preferences::blobs["pool-slider/ticks-v1"]; }

int main() {
  // ---- validation ----
  SliderTuning d;
  assert(d.valid() && sizeof(d) == 32);
  // Defaults keep 2.7.0's filter and sensor timing; only the defect fixes differ.
  assert(d.minCutoffHz == OneEuroFilter::MIN_CUTOFF_HZ && d.beta == OneEuroFilter::BETA);
  assert(d.enterFrac == .33f && d.timingBudgetMs == 20 && d.confirmMs == 50);
  assert(d.exitFrac > d.enterFrac && d.releaseMs > 0 && d.dropoutMs >= 400);
  { SliderTuning t=d; t.timingBudgetMs=5; assert(!t.valid()); }      // sensor minimum
  { SliderTuning t=d; t.timingBudgetMs=201; assert(!t.valid()); }
  { SliderTuning t=d; t.intervalMs=20; assert(!t.valid()); }          // must exceed budget
  { SliderTuning t=d; t.intervalMs=21; assert(t.valid()); }
  { SliderTuning t=d; t.medianWindow=4; assert(!t.valid()); }         // even has no middle
  { SliderTuning t=d; t.medianWindow=0; assert(!t.valid()); }
  { SliderTuning t=d; t.exitFrac=t.enterFrac-.01f; assert(!t.valid()); }  // anti-hysteresis
  { SliderTuning t=d; t.exitFrac=.95f; assert(!t.valid()); }          // un-releasable
  { SliderTuning t=d; t.enterFrac=.6f; assert(!t.valid()); }          // overlapping windows
  { SliderTuning t=d; t.minCutoffHz=NAN; assert(!t.valid()); }
  { SliderTuning t=d; t.dropoutMs=5000; assert(!t.valid()); }
  assert(d.pollIntervalMs() > 0 && d.pollIntervalMs() < d.timingBudgetMs);
  assert(d.staleMs() > d.dropoutMs);  // the watchdog must never pre-empt dropout tolerance

  // ---- hysteresis in select() ----
  SliderCalibration c;
  for (int i=0;i<23;++i) c.mm[i]=100+10*i;  // 10 mm pitch, ascending
  assert(c.valid());
  // Held members keep a wider window than they needed to enter.
  assert(c.select(104.f, -1, .33f, .45f) == -1);   // outside the enter window
  assert(c.select(104.f, 1, .33f, .45f) == 1);     // inside the exit window when held
  // exitFrac above 0.5 must actually widen, not silently cap: tick 2 is at 110 mm.
  assert(c.select(107.f, 1, .33f, .8f) == 1);
  assert(c.select(107.f, -1, .33f, .8f) == 2);
  // A held member is always releasable: its window never reaches the neighbour's centre.
  for (float frac : {.5f, .8f, .9f, 5.f}) assert(c.select(110.f, 1, .33f, frac) == 2);
  // Clamping: anti-hysteresis is rejected rather than inverting the behaviour.
  assert(c.select(104.f, 1, .33f, .1f) == c.select(104.f, 1, .33f, .33f));
  // Endpoints use their sole neighbour, in both directions.
  assert(c.select(96.f, 1, .33f, .45f) == 1 && c.select(324.f, 23, .33f, .45f) == 23);
  assert(c.select(NAN, 12, .33f, .45f) == -1);
  // Equal fracs reproduce the original mapping exactly, for every held value.
  for (int held=-1; held<=23; ++held)
    for (float mm=90.f; mm<=330.f; mm+=0.37f)
      assert(c.select(mm, held, .33f, .33f) == c.select(mm));

  // ---- median prefilter ----
  MedianFilter m; m.configure(3);
  m.update(200); m.update(200);
  assert(fabsf(m.update(400)-200) < 1);   // an isolated spike is rejected outright
  m.configure(4); assert(m.window()==3);  // even rounds down to odd
  m.configure(99); assert(m.window()==9);
  MedianFilter one; one.configure(1); assert(one.update(400)==400);  // window 1 disables

  // ---- live commands on the real sketch ----
  image("zdb_a", SLOT_V1); image("zdb_b", {}); image("zcfg", CONFIG_POOL4);
  laserDistance=383; setup(); run(300);
  assert(confirmedPosition==1 && !rawStream);            // RAW is never persisted
  auto ticksBefore = savedTicks();
  assert(!savedTuning() && tuningSaved==false);          // nothing written on boot
  assert(has(serial("TUNE GET"), "\"type\":\"tuning\""));
  assert(has(serial("TUNE GET"), "\"defaults\""));

  // A rejected value leaves the live tuning untouched.
  float beforeCutoff = tuning.minCutoffHz;
  assert(has(serial("TUNE SET mincutoff 999"), "ERR TUNE SET"));
  assert(tuning.minCutoffHz == beforeCutoff);
  assert(has(serial("TUNE SET budget 5"), "ERR TUNE SET") && tuning.timingBudgetMs==20);
  assert(has(serial("TUNE SET median 4"), "ERR TUNE SET") && tuning.medianWindow==3);
  assert(has(serial("TUNE SET nonsense 1"), "ERR TUNE SET"));
  // Negative and huge values must not reach an integer cast (UBSan would trap).
  assert(has(serial("TUNE SET confirm -5"), "ERR TUNE SET"));
  assert(has(serial("TUNE SET confirm 1e30"), "ERR TUNE SET"));
  assert(has(serial("TUNE SET release nan"), "ERR TUNE SET"));

  // Accepted values apply live, without pausing output and without touching flash.
  serial("TUNE SET exit 0.6");
  assert(fabsf(tuning.exitFrac-0.6f) < 1e-5 && !tuningSaved && !savedTuning());
  serial("TUNE SET budget 50");
  assert(tuning.timingBudgetMs==50 && laserBudgetMs==50 && tuning.pollIntervalMs()==25);
  assert(!calibrationEditing);  // tuning must not gate output the way CAL SET does

  // Save, restart, and confirm the calibration blob is untouched by a tuning save.
  assert(has(serial("TUNE SAVE"), "OK TUNE SAVE") && tuningSaved && savedTuning());
  assert(savedTicks() == ticksBefore);
  setup(); run(200);
  assert(tuningSaved && tuning.timingBudgetMs==50 && fabsf(tuning.exitFrac-0.6f) < 1e-5);
  assert(calibration.mm[0]==383);  // calibration survived

  // Defaults are applied live but never written.
  assert(has(serial("TUNE DEFAULTS"), "OK TUNE DEFAULTS"));
  assert(tuning.timingBudgetMs==20 && !tuningSaved && savedTuning());
  assert(has(serial("TUNE LOAD"), "OK TUNE LOAD") && tuning.timingBudgetMs==50);

  // A corrupt blob falls back to defaults without writing or erroring at boot.
  Preferences::blobs["pool-slider/tune-v1"].resize(7);
  setup(); run(200);
  assert(!tuningSaved && tuning.timingBudgetMs==20 && calibration.mm[0]==383);

  // A saved timing the sensor rejects must not leave the slider dead at every boot.
  { SliderTuning bad; bad.timingBudgetMs=20; bad.intervalMs=0;
    Preferences::blobs["pool-slider/tune-v1"].assign((uint8_t*)&bad,(uint8_t*)&bad+sizeof(bad)); }
  laserBudgetMs=0; setup(); run(100);
  assert(laserOk && laserBudgetMs==20);

  // ---- RAW streaming ----
  assert(has(serial("RAW ON"), "OK RAW ON") && rawStream);
  std::string stream = serial("HOST STATUS", 120);
  assert(has(stream, "\"type\":\"raw\"") && has(stream, "\"st\":"));
  laserStatus=4; std::string bad = serial("HOST STATUS", 120);
  assert(has(bad, "\"mm\":null") && has(bad, "\"f\":null"));  // honest about a bad read
  laserStatus=0;
  assert(has(serial("RAW OFF"), "OK RAW OFF") && !rawStream);
  assert(has(serial("RAW MAYBE"), "ERR RAW"));
  setup(); assert(!rawStream);

  puts("PASS: SliderTuning validation, hysteresis window, median prefilter, live TUNE apply/save/load, NVS key isolation, sensor-timing fallback, RAW stream");
}
