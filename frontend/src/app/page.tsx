import { redirect } from 'next/navigation';

export default function Home() {
  // Land on a default household. Backend auto-creates an empty plan if it
  // doesn't exist yet, so the workspace renders immediately.
  redirect('/plan/me');
}
