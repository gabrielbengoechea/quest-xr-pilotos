"""Máscara de tierra equirectangular a partir de world-atlas (Natural Earth 1:50m)."""
import json, sys
from PIL import Image, ImageDraw

def unwrap(ring):
    out=[list(ring[0])]
    for x,y in ring[1:]:
        px=out[-1][0]
        while x-px>180: x-=360
        while x-px<-180: x+=360
        out.append([x,y])
    return out

def mask(W=2048,H=1024,src='land50.json'):
    P=json.load(open(src))
    im=Image.new('L',(W,H),0); d=ImageDraw.Draw(im)
    for poly in P:
        for k,ring in enumerate(poly):
            r=unwrap(ring)
            drift=r[-1][0]-r[0][0]
            if abs(drift)>180:          # anillo que rodea un polo (Antártida): cerrarlo por el polo
                pole=-90 if sum(y for _,y in r)/len(r)<0 else 90
                r=r+[[r[-1][0],pole],[r[0][0],pole]]
            for sh in (-360,0,360):
                pts=[((x+sh+180)/360*W,(90-y)/180*H) for x,y in r]
                d.polygon(pts,fill=255 if k==0 else 0)
    return im

if __name__=='__main__':
    im=mask(); im.save('land_mask.png'); im.resize((1024,512)).save(sys.argv[1] if len(sys.argv)>1 else 'm.png')
