import React, { useState } from 'react';
import { useNewsStore } from '@/stores/newsStore';
import { X, Check, ChevronsUpDown } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { Command, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList } from '@/components/ui/command';
import { cn } from '@/lib/utils';

export function TagSelector() {
  const { availableTags, archiveFilters, addTagFilter, removeTagFilter } = useNewsStore();
  const [open, setOpen] = useState(false);

  return (
    <div className="flex flex-wrap items-center gap-2">
      {archiveFilters.tags.map(tag => (
        <Badge key={tag} variant="secondary" className="px-2 py-1 flex items-center gap-1 bg-blue-50 text-blue-700 hover:bg-blue-100">
          {tag}
          <X 
            className="w-3 h-3 cursor-pointer hover:text-blue-900" 
            onClick={() => removeTagFilter(tag)}
          />
        </Badge>
      ))}

      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger
          className="inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-md text-xs font-medium ring-offset-background transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:pointer-events-none disabled:opacity-50 border border-input bg-background hover:bg-accent hover:text-accent-foreground h-8 px-3 border-dashed"
        >
          + 添加标签
          <ChevronsUpDown className="ml-2 h-3 w-3 shrink-0 opacity-50" />
        </PopoverTrigger>
        <PopoverContent className="w-[200px] p-0" align="start">
          <Command>
            <CommandInput placeholder="搜索标签..." />
            <CommandList>
              <CommandEmpty>未找到标签</CommandEmpty>
              <CommandGroup>
                {availableTags.map((tagObj) => (
                  <CommandItem
                    key={tagObj.tag}
                    value={tagObj.tag}
                    onSelect={(currentValue) => {
                      addTagFilter(currentValue);
                      setOpen(false);
                    }}
                  >
                    <Check
                      className={cn(
                        "mr-2 h-4 w-4",
                        archiveFilters.tags.includes(tagObj.tag) ? "opacity-100" : "opacity-0"
                      )}
                    />
                    {tagObj.tag}
                    <span className="ml-auto text-xs text-gray-400">{tagObj.count}</span>
                  </CommandItem>
                ))}
              </CommandGroup>
            </CommandList>
          </Command>
        </PopoverContent>
      </Popover>
    </div>
  );
}
