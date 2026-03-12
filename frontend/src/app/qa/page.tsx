'use client'

import { useEffect } from 'react'
import { useRouter } from 'next/navigation'

export default function QARedirect() {
  const router = useRouter()
  useEffect(() => {
    router.replace('/chat')
  }, [router])
  return (
    <div className="min-h-screen bg-[#F5F5F7] flex items-center justify-center">
      <p className="text-gray-500">正在跳转到智能问答...</p>
    </div>
  )
}
