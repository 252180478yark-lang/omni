import { redirect } from 'next/navigation'

export default function WorkspaceDevelopmentAlias() {
  redirect('/workspace?mode=development')
}
