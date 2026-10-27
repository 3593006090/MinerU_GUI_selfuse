"""生成一个最小可用的测试 PDF（Helvetica 文本 + 简单图形）。"""
import zlib

W, H = 595, 842
lines = [
    (18, "MinerU Local Deployment Test"),
    (12, "Section 1: Introduction"),
    (11, "This document verifies that MinerU can parse text, formulas and tables locally."),
    (11, "Section 2: Formula"),
    (11, "The quadratic formula is x = (-b +/- sqrt(b^2 - 4ac)) / (2a)."),
    (11, "Section 3: Table"),
    (11, "Name       City       Job"),
    (11, "Zhang San  Beijing    Engineer"),
    (11, "Li Si      Shanghai   Designer"),
    (11, "Section 4: Conclusion"),
    (11, "If all content above is extracted correctly, the deployment works."),
]

parts = []
y = H - 80
for size, text in lines:
    esc = text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")
    parts.append(f"BT /F1 {size} Tf 72 {y} Td ({esc}) Tj ET")
    y -= max(20, size + 10)

stream = "\n".join(parts).encode("latin-1")

objs = []
objs.append(b"<< /Type /Catalog /Pages 2 0 R >>")
objs.append(b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>")
objs.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {W} {H}] "
            f"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>".encode())
objs.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
objs.append(b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream")

out = bytearray(b"%PDF-1.4\n")
offsets = [0]
for i, body in enumerate(objs, start=1):
    offsets.append(len(out))
    out += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"

xref_pos = len(out)
out += f"xref\n0 {len(objs)+1}\n".encode()
out += b"0000000000 65535 f \n"
for off in offsets[1:]:
    out += f"{off:010d} 00000 n \n".encode()
out += f"trailer\n<< /Size {len(objs)+1} /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF\n".encode()

with open(r"E:\MinerU\test\sample.pdf", "wb") as f:
    f.write(out)
print("written", len(out), "bytes")
