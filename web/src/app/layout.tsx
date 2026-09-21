import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "NCT Inventory",
  description: "Shared device inventory for the NCT Neocore installation",
  robots: { index: false, follow: false },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
