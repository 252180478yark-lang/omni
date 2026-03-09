$msgPath = $args[0]
$counterFile = Join-Path $PWD ".git/rebase-msg-count"
$count = 0
if (Test-Path $counterFile) { $count = [int](Get-Content $counterFile) }
$count++
Set-Content $counterFile $count -NoNewline
if ($count -eq 1) {
  Get-Content ".git-commit-msg-2.txt" -Raw -Encoding UTF8 | Set-Content $msgPath -Encoding UTF8 -NoNewline
} else {
  Get-Content ".git-commit-msg-1.txt" -Raw -Encoding UTF8 | Set-Content $msgPath -Encoding UTF8 -NoNewline
}
