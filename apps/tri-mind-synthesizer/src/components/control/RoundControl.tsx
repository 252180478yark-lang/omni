import { Minus, Plus } from 'lucide-react'
import { cn } from '../../lib/utils'

interface RoundControlProps {
  rounds: number
  onRoundsChange: (rounds: number) => void
  min?: number
  max?: number
  disabled?: boolean
}

/**
 * 辩论轮数控制组件
 * 
 * 提供 +/- 按钮调节辩论轮数（1-5轮），
 * 并显示每个轮数的简要说明。
 */
export function RoundControl({
  rounds,
  onRoundsChange,
  min = 1,
  max = 5,
  disabled = false,
}: RoundControlProps) {
  const handleDecrease = () => {
    if (rounds > min) onRoundsChange(rounds - 1)
  }

  const handleIncrease = () => {
    if (rounds < max) onRoundsChange(rounds + 1)
  }

  // 轮数说明
  const getRoundDescription = () => {
    switch (rounds) {
      case 1: return '单轮回答'
      case 2: return '一轮交叉评审'
      case 3: return '两轮交叉评审'
      case 4: return '三轮深度辩论'
      case 5: return '四轮深度辩论'
      default: return ''
    }
  }

  return (
    <div className="flex items-center gap-2">
      <span className="text-sm text-gray-500">辩论轮数:</span>
      <div className="flex items-center gap-1">
        <button
          onClick={handleDecrease}
          disabled={disabled || rounds <= min}
          className={cn(
            'p-1 rounded-lg hover:bg-gray-100 transition-colors',
            (disabled || rounds <= min) && 'opacity-50 cursor-not-allowed'
          )}
          title="减少轮数"
        >
          <Minus className="w-4 h-4" />
        </button>

        {/* 轮数显示 - 带进度点 */}
        <div className="flex items-center gap-1 px-2">
          {Array.from({ length: max }, (_, i) => (
            <div
              key={i}
              className={cn(
                'w-2 h-2 rounded-full transition-colors',
                i < rounds
                  ? 'bg-blue-500'
                  : 'bg-gray-300/40'
              )}
            />
          ))}
        </div>
        
        <span className="w-6 text-center text-sm font-medium">{rounds}</span>

        <button
          onClick={handleIncrease}
          disabled={disabled || rounds >= max}
          className={cn(
            'p-1 rounded-lg hover:bg-gray-100 transition-colors',
            (disabled || rounds >= max) && 'opacity-50 cursor-not-allowed'
          )}
          title="增加轮数"
        >
          <Plus className="w-4 h-4" />
        </button>
      </div>

      {/* 轮数说明 */}
      <span className="text-xs text-gray-500 hidden sm:inline">
        ({getRoundDescription()})
      </span>
    </div>
  )
}
