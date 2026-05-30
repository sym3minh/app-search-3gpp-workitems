# _setup.ps1 - duoc goi boi Tao_Shortcut_Desktop.bat

$ErrorActionPreference = "Continue"

$appDir   = Split-Path -Parent $MyInvocation.MyCommand.Path
$appPy    = Join-Path $appDir "sources\app.py"
$iconFile = Join-Path $appDir "icon.ico"

Write-Host ""
Write-Host "  3GPP Search - Cai dat shortcut" -ForegroundColor Cyan
Write-Host "  ================================" -ForegroundColor Cyan
Write-Host ""

# --- Tim pythonw.exe ---
$pythonw = $null

$pyCmd = Get-Command "pythonw.exe" -ErrorAction SilentlyContinue
if ($pyCmd) {
    $pythonw = $pyCmd.Source
}

if (-not $pythonw) {
    $candidates = @(
        "$env:LOCALAPPDATA\Programs\Python\Python313\pythonw.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python312\pythonw.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python311\pythonw.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python310\pythonw.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python39\pythonw.exe",
        "C:\Python313\pythonw.exe",
        "C:\Python312\pythonw.exe",
        "C:\Python311\pythonw.exe",
        "C:\Python310\pythonw.exe"
    )
    foreach ($c in $candidates) {
        if (Test-Path $c) {
            $pythonw = $c
            break
        }
    }
}

if (-not $pythonw) {
    $pyCmd2 = Get-Command "python.exe" -ErrorAction SilentlyContinue
    if ($pyCmd2) {
        $pyDir = Split-Path $pyCmd2.Source
        $candidate = Join-Path $pyDir "pythonw.exe"
        if (Test-Path $candidate) {
            $pythonw = $candidate
        }
    }
}

if (-not $pythonw) {
    Write-Host "  [LOI] Khong tim thay Python!" -ForegroundColor Red
    Write-Host ""
    Write-Host "  -> Cai Python tai: https://python.org/downloads" -ForegroundColor Yellow
    Write-Host "     Khi cai nho tick: Add Python to PATH" -ForegroundColor Yellow
    Write-Host ""
    Read-Host "  Nhan Enter de thoat"
    exit 1
}

Write-Host "  [OK] Python: $pythonw" -ForegroundColor Green

# --- Kiem tra va cai dependencies ---
# Dung file tam de tranh loi quoting khi goi python -c
$checkScript = Join-Path $env:TEMP "gpp_check.py"

$depModules = @("openpyxl", "requests", "bs4", "docx", "numpy", "sklearn", "sentence_transformers", "transformers", "umap", "hdbscan", "chromadb", "webview")
$depPkgs    = @("openpyxl", "requests", "beautifulsoup4", "python-docx", "numpy", "scikit-learn", "sentence-transformers", "transformers", "umap-learn", "hdbscan", "chromadb", "pywebview")

for ($i = 0; $i -lt $depModules.Length; $i++) {
    $mod = $depModules[$i]
    $pkg = $depPkgs[$i]

    Write-Host "  [..] Kiem tra $mod..." -ForegroundColor Cyan

    $pyCode = "import " + $mod + [System.Environment]::NewLine + "print('ok')"
    [System.IO.File]::WriteAllText($checkScript, $pyCode, [System.Text.Encoding]::UTF8)

    $result = & python $checkScript 2>&1
    $resultStr = ($result | Out-String).Trim()

    if ($resultStr -eq "ok") {
        Write-Host "  [OK] $mod san sang." -ForegroundColor Green
    } else {
        Write-Host "  [..] Dang cai $pkg..." -ForegroundColor Yellow
        & python -m pip install $pkg --quiet 2>&1 | Out-Null
        $result2 = & python $checkScript 2>&1
        $result2Str = ($result2 | Out-String).Trim()
        if ($result2Str -eq "ok") {
            Write-Host "  [OK] Da cai xong $pkg." -ForegroundColor Green
        } else {
            Write-Host "  [WARN] Cai $pkg that bai. Chay thu: pip install $pkg" -ForegroundColor Yellow
        }
    }
}

if (Test-Path $checkScript) {
    Remove-Item $checkScript -Force
}

# --- Tao shortcut tren Desktop ---
$desktop      = [Environment]::GetFolderPath("Desktop")
$shortcutPath = Join-Path $desktop "3GPP Search.lnk"

$shell    = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath       = $pythonw
$shortcut.Arguments        = "`"$appPy`""
$shortcut.WorkingDirectory = $appDir   # giu o thu muc goc de cache/ va output/ tao o day
$shortcut.Description      = "3GPP Work Item Search"
$shortcut.WindowStyle      = 1

if (Test-Path $iconFile) {
    $shortcut.IconLocation = $iconFile
} else {
    $shortcut.IconLocation = "$pythonw,0"
}
$shortcut.Save()

Write-Host "  [OK] Shortcut da tao: $shortcutPath" -ForegroundColor Green
Write-Host ""
Write-Host "  => Double-click 3GPP Search tren Desktop de mo app." -ForegroundColor White
Write-Host "     Co the gim vao Taskbar: chuot phai shortcut > Pin to taskbar" -ForegroundColor Gray
Write-Host ""
Read-Host "  Nhan Enter de thoat"
