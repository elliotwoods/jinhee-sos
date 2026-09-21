export const metadata = { title: "Sign in · NCT Inventory" };

export default async function LoginPage({ searchParams }: { searchParams: Promise<{ error?: string }> }) {
  const { error } = await searchParams;
  return (
    <main className="login">
      <form className="card login-card" method="post" action="/api/session">
        <h1>NCT / DEVICE INVENTORY</h1>
        <p className="muted">Enter the shared inventory password.</p>
        <label htmlFor="password">Password</label>
        <input id="password" name="password" type="password" autoComplete="current-password" autoFocus required />
        {error && <p className="bad">Wrong password — try again.</p>}
        <button className="primary" type="submit">Sign in</button>
      </form>
    </main>
  );
}
