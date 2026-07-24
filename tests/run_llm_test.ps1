# 临时脚本：绕过 sandbox 中文路径限制，直接调用 LLM
param(
    [string]$InputData = '{"data_type":"prompt","content":"你好，介绍一下你自己，20字以内"}'
)

$llmMain = Join-Path $PSScriptRoot "..\nodes\node_python_llm_infer\main.py"
$llmPython = Join-Path $PSScriptRoot "..\nodes\node_python_llm_infer\venv\Scripts\python.exe"

if (-not (Test-Path $llmPython)) {
    Write-Host "[FAIL] LLM venv 不存在: $llmPython"
    exit 1
}

Write-Host "====== LLM 推理测试 ======"
Write-Host "输入: $InputData"
Write-Host ""

$result = & $llmPython $llmMain $InputData
Write-Host "输出:"
Write-Host $result
