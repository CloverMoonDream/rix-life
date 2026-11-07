param([string]$Out = "$env:TEMP\screen.png", [int]$MaxWidth = 1280)
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$vs = [System.Windows.Forms.SystemInformation]::VirtualScreen
$bmp = New-Object System.Drawing.Bitmap $vs.Width, $vs.Height
$g = [System.Drawing.Graphics]::FromImage($bmp)
$g.CopyFromScreen($vs.X, $vs.Y, 0, 0, $bmp.Size)
$g.Dispose()
$scale = [Math]::Min(1.0, $MaxWidth / $bmp.Width)
if ($scale -lt 1.0) {
  $nw = [int]($bmp.Width * $scale); $nh = [int]($bmp.Height * $scale)
  $small = New-Object System.Drawing.Bitmap $nw, $nh
  $g2 = [System.Drawing.Graphics]::FromImage($small)
  $g2.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
  $g2.DrawImage($bmp, 0, 0, $nw, $nh)
  $g2.Dispose()
  $small.Save($Out, [System.Drawing.Imaging.ImageFormat]::Png)
  $small.Dispose()
} else {
  $bmp.Save($Out, [System.Drawing.Imaging.ImageFormat]::Png)
}
$bmp.Dispose()
"$Out|$($vs.Width)x$($vs.Height)"