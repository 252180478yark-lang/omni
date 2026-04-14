export interface Persona {
  id: string
  name: string
  icon: string
  description: string
  systemPrompt: string
  exampleQueries: string[]
  isPreset: boolean
  createdAt: number
  updatedAt: number
}
