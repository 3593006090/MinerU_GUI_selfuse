$ErrorActionPreference = 'Stop'

$Proj   = 'E:\MinerU\install-gui'
$Root   = 'E:\MinerU'
$Build  = Join-Path $Proj '.build'
$Venv   = Join-Path $Build 'venv'
$Dist   = Join-Path $Proj 'dist'
$Bundle = Join-Path $Proj 'src\bundle'
$Src    = Join-Path $Proj 'src'

New-Item -ItemType Directory -Force $Build, $Dist, (Join-Path $Proj 'assets') | Out-Null

Write-Host '==> step 1/5: prepare build venv'
if (-not (Test-Path (Join-Path $Venv 'Scripts\python.exe'))) {
    python -m uv venv --python 3.12 $Venv | Out-Null
}
$Bpy = Join-Path $Venv 'Scripts\python.exe'
python -m uv pip install --python $Bpy pyinstaller pillow -i https://mirrors.aliyun.com/pypi/simple --quiet | Out-Null

Write-Host '==> step 2/5: generate icon'
& $Bpy (Join-Path $Proj 'assets\make_icon.py')

Write-Host '==> step 3/5: collect bundled resources'
if (Test-Path $Bundle) { Remove-Item -Recurse -Force $Bundle }
New-Item -ItemType Directory -Force (Join-Path $Bundle 'scripts'), (Join-Path $Bundle 'docs'), (Join-Path $Bundle 'webapp\static') | Out-Null
Copy-Item (Join-Path $Root 'webapp\server.py') (Join-Path $Bundle 'webapp\server.py')
Get-ChildItem (Join-Path $Root 'webapp\static') -File |
    Where-Object { $_.Extension -in '.html', '.css', '.js' } |
    Copy-Item -Destination (Join-Path $Bundle 'webapp\static')
Copy-Item (Join-Path $Root 'bin\stop.ps1') (Join-Path $Bundle 'scripts\stop.ps1')
Copy-Item (Join-Path $Root 'README-部署说明.md') (Join-Path $Bundle 'docs') -ErrorAction SilentlyContinue
Copy-Item (Join-Path $Root 'DSH-集成说明.md') (Join-Path $Bundle 'docs') -ErrorAction SilentlyContinue

Write-Host '==> step 4/5: pyinstaller (onedir: no temp extraction at runtime)'
$Pyi  = Join-Path $Venv 'Scripts\pyinstaller.exe'
$Icon = Join-Path $Proj 'assets\icon.ico'

& $Pyi --noconfirm --clean --onedir --windowed --name minerU-install-gui --icon $Icon --paths $Src --add-data "$Bundle;bundle" --distpath $Dist --workpath (Join-Path $Build 'work-installer') --specpath $Build (Join-Path $Src 'installer_main.py')

& $Pyi --noconfirm --clean --onedir --windowed --name minerU-gui --icon $Icon --paths $Src --distpath $Dist --workpath (Join-Path $Build 'work-launcher') --specpath $Build (Join-Path $Src 'launcher_main.py')

Write-Host '==> step 5/5: deploy folders to install root'
foreach ($name in 'minerU-install-gui', 'minerU-gui') {
    $target = Join-Path $Root $name
    if (Test-Path $target) { Remove-Item -Recurse -Force $target -ErrorAction SilentlyContinue }
    Copy-Item -Recurse (Join-Path $Dist $name) $target
}
foreach ($stale in 'minerU-gui.exe', 'minerU-install-gui.exe') {
    $p = Join-Path $Root $stale
    if (Test-Path $p) { Remove-Item -Force $p -ErrorAction SilentlyContinue }
}

Write-Host ''
Write-Host ('  GUI:       ' + (Join-Path $Root 'minerU-gui\minerU-gui.exe'))
Write-Host ('  Installer: ' + (Join-Path $Root 'minerU-install-gui\minerU-install-gui.exe'))
