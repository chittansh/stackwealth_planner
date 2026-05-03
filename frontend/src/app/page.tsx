import { redirect } from 'next/navigation';

export default function Home() {
  // RM mode: landing is the client list. Pick a client from there or create one.
  redirect('/advisor/clients');
}
