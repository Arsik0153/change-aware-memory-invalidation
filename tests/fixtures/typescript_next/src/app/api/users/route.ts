import { createUser as saveUser } from '../../../lib/users';
export async function POST() {
  return saveUser('Ada');
}
