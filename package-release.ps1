$ErrorActionPreference = "Stop"
$PSNativeCommandUseErrorActionPreference = $true

$versionMatch = Select-String -LiteralPath "$PSScriptRoot\pyproject.toml" -Pattern '^version = "([^"]+)"$'
if (-not $versionMatch) {
    throw "Could not read the project version from pyproject.toml."
}
$version = $versionMatch.Matches[0].Groups[1].Value
if ($version -notmatch '^\d+\.\d+\.\d+$') {
    throw "Unexpected project version: $version"
}

& "$PSScriptRoot\build.ps1"

$releaseRoot = Join-Path $PSScriptRoot "release"
$appFolderName = "FrameLab-v$version-win64"
$appStaging = Join-Path $releaseRoot $appFolderName
$appArchive = Join-Path $releaseRoot "$appFolderName.zip"
$sourceFolderName = "FrameLab-v$version-ffmpeg-sources"
$sourceStaging = Join-Path $releaseRoot $sourceFolderName
$sourceArchive = Join-Path $releaseRoot "$sourceFolderName.zip"

New-Item -ItemType Directory -Force -Path $releaseRoot | Out-Null
foreach ($path in ($appStaging, $appArchive, $sourceStaging, $sourceArchive)) {
    if (Test-Path -LiteralPath $path) {
        throw "Release output already exists: $path"
    }
}

New-Item -ItemType Directory -Path $appStaging | Out-Null
Copy-Item -Path "$PSScriptRoot\dist\FrameLab\*" -Destination $appStaging -Recurse
Compress-Archive -LiteralPath $appStaging -DestinationPath $appArchive -CompressionLevel Optimal

New-Item -ItemType Directory -Path $sourceStaging | Out-Null
Copy-Item -Path "$PSScriptRoot\build\ffmpeg-minimal\dist\sources\*" -Destination $sourceStaging
Copy-Item -LiteralPath "$PSScriptRoot\tools\build_minimal_ffmpeg.sh" -Destination $sourceStaging
Copy-Item -LiteralPath "$PSScriptRoot\vendor\ffmpeg\BUILD-INFO.txt" -Destination $sourceStaging
Copy-Item -LiteralPath "$PSScriptRoot\vendor\ffmpeg\FFmpeg-COPYING.GPLv2.txt" -Destination $sourceStaging
Copy-Item -LiteralPath "$PSScriptRoot\vendor\ffmpeg\x264-COPYING.txt" -Destination $sourceStaging
Compress-Archive -LiteralPath $sourceStaging -DestinationPath $sourceArchive -CompressionLevel Optimal

$checksums = foreach ($archive in ($appArchive, $sourceArchive)) {
    $hash = Get-FileHash -LiteralPath $archive -Algorithm SHA256
    "$($hash.Hash.ToLowerInvariant())  $([IO.Path]::GetFileName($archive))"
}
Set-Content -LiteralPath (Join-Path $releaseRoot "SHA256SUMS.txt") -Value $checksums -Encoding utf8NoBOM

Write-Host "Packaged FrameLab $version in $releaseRoot"
