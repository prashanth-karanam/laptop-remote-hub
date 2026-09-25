
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

 = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
 = New-Object System.Drawing.Bitmap .Width, .Height
 = [System.Drawing.Graphics]::FromImage()
.CopyFromScreen([System.Drawing.Point]::Empty, [System.Drawing.Point]::Empty, .Size)
.Save('test_screen.jpg', [System.Drawing.Imaging.ImageFormat]::Jpeg)
.Dispose()
.Dispose()
