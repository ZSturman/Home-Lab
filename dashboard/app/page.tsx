import { Dashboard } from "../components/dashboard";

export default function Page() {
  return <Dashboard platformName={process.env.NEXT_PUBLIC_PLATFORM_NAME ?? "Home Platform"} />;
}
