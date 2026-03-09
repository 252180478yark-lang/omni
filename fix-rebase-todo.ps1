$path = $args[0]
(Get-Content $path -Raw) -replace '^pick ', 'reword ' | Set-Content $path -NoNewline
