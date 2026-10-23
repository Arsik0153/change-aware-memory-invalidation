import { registerUser } from '@/lib';
export default function UserForm() {
  const handleSubmit = async (name: string) => registerUser(name);
  return <form onSubmit={handleSubmit} />;
}
