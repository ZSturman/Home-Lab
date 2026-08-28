import type { Metadata } from "next";
import "./styles.css";

export const metadata: Metadata = {
  title: "Home Platform",
  description: "Private home-lab Control Plane",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en"><body>{children}</body></html>;
}
