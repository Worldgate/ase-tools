import struct,sys,json,collections
class R:
    def __init__(s,d,o=0): s.d=d; s.o=o
    def i32(s): v=struct.unpack_from('<i',s.d,s.o)[0]; s.o+=4; return v
    def s(s):
        n=s.i32()
        if n==0: return ''
        if n<0: b=s.d[s.o:s.o-n*2]; s.o+=-n*2; return b.decode('utf-16le').rstrip('\0')
        b=s.d[s.o:s.o+n]; s.o+=n; return b.decode('latin1').rstrip('\0')
SIMPLE={'IntProperty':'<i','UInt32Property':'<I','FloatProperty':'<f','DoubleProperty':'<d','UInt16Property':'<H','Int16Property':'<h','UInt64Property':'<Q','Int64Property':'<q','Int8Property':'<b'}
NATIVE={'Vector':'<3f','Rotator':'<3f','Vector2D':'<2f','Quat':'<4f','LinearColor':'<4f','Color':'<4B','IntPoint':'<2i'}
def props(r,end=None):
    out=[]
    while end is None or r.o<end:
        name=r.s()
        if name=='None': break
        t=r.s(); size=r.i32(); idx=r.i32()
        if t=='BoolProperty':
            out.append((name,idx,t,r.d[r.o])); r.o+=1; continue
        sub=None
        if t in('StructProperty','ArrayProperty','ByteProperty'): sub=r.s()
        start=r.o
        try: v=value(r,t,sub,size)
        except Exception as e: v=f'<err {e} {size}b>'
        r.o=start+size
        out.append((name,idx,t+(f'<{sub}>' if sub else ''),v))
    return out
def value(r,t,sub,size):
    d=r.d
    if t in SIMPLE: return struct.unpack_from(SIMPLE[t],d,r.o)[0]
    if t in('StrProperty','NameProperty'): return r.s()
    if t=='ByteProperty': return d[r.o] if sub=='None' else r.s()
    if t=='ObjectProperty':
        return {'path':r.s()} if size>4 else {'id':r.i32()}
    if t=='StructProperty':
        if sub in NATIVE: return list(struct.unpack_from(NATIVE[sub],d,r.o))
        return props(r,r.o+size)
    if t=='ArrayProperty':
        end=r.o+size; n=r.i32()
        if sub=='ByteProperty': return f'<{n} bytes>'
        if sub in SIMPLE: return list(struct.unpack_from('<'+str(n)+SIMPLE[sub][1],d,r.o))
        if sub in('StrProperty','NameProperty'): return [r.s() for _ in range(n)]
        if sub=='ObjectProperty':
            out=[]
            for _ in range(n):
                k=r.i32(); out.append({'id':r.i32()} if k==0 else {'path':r.s()})
            return out
        if sub=='StructProperty':
            # UE4 array-of-struct header: name, "StructProperty", size, index, struct type, 16-byte guid
            # ARK SaveGame: no UE4 array header; each element is its own property list
            stype='struct'; hdr_name=''
            items=[]
            for _ in range(n):
                if r.o>=end: break
                items.append(props(r,end))
            return {'_struct':stype,'_hdr':hdr_name,'items':items}
        return f'<array {sub} n={n} {size}b>'
    return f'<{t} {size}b>'
def show(p,ind=0,maxitems=3):
    for name,idx,t,v in p:
        lab=f"{'  '*ind}{name}{'['+str(idx)+']' if idx else ''} : {t}"
        if isinstance(v,list) and v and isinstance(v[0],tuple):
            print(lab); show(v,ind+1,maxitems)
        elif isinstance(v,dict) and 'items' in v:
            print(lab, f"[{len(v['items'])} x {v['_struct']}]")
            for i,it in enumerate(v['items'][:maxitems]):
                print(f"{'  '*(ind+1)}-- #{i}"); show(it,ind+2,maxitems)
        else:
            s=json.dumps(v) if not isinstance(v,str) else repr(v)
            print(lab,'=',s[:150])
if __name__=='__main__':
    d=open(sys.argv[1],'rb').read(); r=R(d)
    cls=r.s(); print('class',cls)
    p=props(r); show(p, maxitems=int(sys.argv[2]) if len(sys.argv)>2 else 3)
    print('consumed',r.o,'of',len(d))
