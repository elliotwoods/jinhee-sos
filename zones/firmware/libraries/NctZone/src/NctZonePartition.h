#pragma once
// Storage backed by a labelled data partition (see the sketch's partitions.csv).
#include <esp_partition.h>
#include "NctZoneDb.h"

namespace nctzone {

class PartitionStorage : public Storage {
 public:
  explicit PartitionStorage(const char *label)
      : partition_(esp_partition_find_first(ESP_PARTITION_TYPE_DATA, ESP_PARTITION_SUBTYPE_ANY, label)) {}
  bool found() const { return partition_ != nullptr; }
  size_t size() const override { return partition_ ? partition_->size : 0; }
  bool read(size_t offset, uint8_t *out, size_t len) override {
    return partition_ && esp_partition_read(partition_, offset, out, len) == ESP_OK;
  }
  bool write(size_t offset, const uint8_t *data, size_t len) override {
    return partition_ && esp_partition_write(partition_, offset, data, len) == ESP_OK;
  }
  bool erase() override {
    return partition_ && esp_partition_erase_range(partition_, 0, partition_->size) == ESP_OK;
  }

 private:
  const esp_partition_t *partition_;
};

}  // namespace nctzone
