"""生成带图片的测试 PDF，用于确认 MinerU 输出目录结构（图片资源位置）。"""
import zlib

W, H = 595, 842
img_w, img_h = 120, 90
# 简单渐变 RGB 图
raw = bytearray()
for y in range(img_h):
    row = bytearray([0])  # filter byte
    for x in range(img_w):
        row += bytes([int(255 * x / img_w), int(255 * y / img_h), 180])
    raw += row
img_data = zlib.compress(bytes(raw))

text = "Image Extraction Test"
stream = f"BT /F1 20 Tf 72 760 Td ({text}) Tj ET\nq 200 0 0 150 72 520 cm /Im1 Do Q".encode()

objs = []
objs.append(b"<< /Type /Catalog /Pages 2 0 R >>")
objs.append(b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>")
objs.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {W} {H}] /Resources << /Font << /F1 4 0 R >> /XObject << /Im1 6 0 R >> >> /Contents 5 0 R >>".encode())
objs.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
objs.append(b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream")
objs.append(f"<< /Type /XObject /Subtype /Image /Width {img_w} /Height {img_h} /ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /FlateDecode /Length {len(img_data)} >>\nstream\n".encode() + img_data + b"\nendstream")

out = bytearray(b"%PDF-1.4\n")
offsets = [0]
for i, body in enumerate(objs, start=1):
    offsets.append(len(out))
    out += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"
xref_pos = len(out)
out += f"xref\n0 {len(objs)+1}\n".encode() + b"0000000000 65535 f \n"
for off in offsets[1:]:
    out += f"{off:010d} 00000 n \n".encode()
out += f"trailer\n<< /Size {len(objs)+1} /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF\n".encode()

with open(r"E:\MinerU\test\sample_img.pdf", "wb") as f:
    f.write(out)
print("written", len(out), "bytes")
