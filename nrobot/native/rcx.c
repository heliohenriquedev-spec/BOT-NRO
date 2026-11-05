/* NRO floor-cell renderer. No network/gameplay writes; only D3D render-state interception.
 * Built for the SHA-pinned VC6 x86 client described in rcx_client.py.
 * Rendering model researched against SimpleROHook's DrawM2E (GPL-3.0).
 * This independent native component is distributed under GPL-3.0-or-later.
 */
#define WIN32_LEAN_AND_MEAN
#define COBJMACROS
#define DIRECTDRAW_VERSION 0x0700
#define DIRECT3D_VERSION 0x0700
#include <windows.h>
#include <d3d.h>
#include <stdint.h>
#include <stdlib.h>
#include <stdio.h>
#include <math.h>
#include <stddef.h>

#ifndef RCX_BUILD_TAG
#define RCX_BUILD_TAG development
#endif
#define RCX_STRING_(x) #x
#define RCX_STRING(x) RCX_STRING_(x)
#define RCX_BUILD_ID RCX_STRING(RCX_BUILD_TAG)
#define MAGIC 0x31584352u
#define CAP 4096
typedef struct { int16_t x,y; DWORD fill,outline,symbol; } Cell;
typedef struct { DWORD skill_id,radius,shape,fill,outline,symbol,unit_type; } Preview;
typedef struct {
    DWORD magic,version,pid;
    volatile LONG enabled,sequence;
    DWORD count,last_feed;
    volatile LONG attached,status,drawn,frames,error;
    DWORD mode_manager,renderer_global;
    char map_name[40];
    DWORD fill,outline;
    Cell cells[CAP];
    DWORD preview_count,selection_preview,selected_id;
    Preview previews[256];
} Shared;
_Static_assert(sizeof(Shared)==72820,"IPC layout must match rcx_renderer.Shared");
typedef struct { float x,y,z,rhw; DWORD color; } Vertex;
typedef HRESULT (WINAPI *SetState)(IDirect3DDevice7*, D3DRENDERSTATETYPE,DWORD);
typedef struct { IDirect3DDevice7Vtbl *table; SetState original; } Binding;
static Shared *shared;
static HMODULE module;
static LONG started,in_draw;
static Binding bindings[8];
static LONG binding_count;
#define DRAW_CAP (CAP+1024)
static Vertex fills[DRAW_CAP*6],lines[DRAW_CAP*16];
static Cell cells[DRAW_CAP];
static Preview previews[256];

static int copy_memory(uintptr_t address,void *out,SIZE_T size) {
    SIZE_T got=0;
    return address>=0x10000 && ReadProcessMemory(GetCurrentProcess(),(void*)address,out,size,&got) && got==size;
}
static DWORD word(uintptr_t address) { DWORD result=0; copy_memory(address,&result,4); return result; }
static int finite_matrix(float *m) {
    for(int i=0;i<12;i++) if(!isfinite(m[i])) return 0;
    for(int c=0;c<3;c++) { float n=m[c]*m[c]+m[c+3]*m[c+3]+m[c+6]*m[c+6]; if(n<.8f || n>1.2f) return 0; }
    return 1;
}
static int project(float x,float y,float z,float *m,float hpc,float vpc,float hw,float hh,Vertex *v) {
    float a=x*m[0]+y*m[3]+z*m[6]+m[9];
    float b=x*m[1]+y*m[4]+z*m[7]+m[10];
    float c=x*m[2]+y*m[5]+z*m[8]+m[11];
    if(!isfinite(c) || c<=10.0f || c>=1500.0f) return 0;
    v->rhw=1.0f/c;
    v->x=a*v->rhw*hpc+hw;
    v->y=b*v->rhw*vpc+hh;
    v->z=(1500.0f/1490.0f)*(c-10.0f)*v->rhw;
    return isfinite(v->x) && isfinite(v->y) && fabsf(v->x)<100000 && fabsf(v->y)<100000;
}
/* Exact ray/triangle intersection against the same GAT used to draw the cells.
 * Client mouse coordinates are read only. No gameplay method or cast is called. */
static int triangle_hit(float *o,float *d,float v[3][3],float *t) {
    float e1[3],e2[3],p[3],q[3],a[3];
    for(int i=0;i<3;i++){e1[i]=v[1][i]-v[0][i];e2[i]=v[2][i]-v[0][i];a[i]=o[i]-v[0][i];}
    p[0]=d[1]*e2[2]-d[2]*e2[1];p[1]=d[2]*e2[0]-d[0]*e2[2];p[2]=d[0]*e2[1]-d[1]*e2[0];
    float det=e1[0]*p[0]+e1[1]*p[1]+e1[2]*p[2];if(fabsf(det)<1e-6f)return 0;
    float u=(a[0]*p[0]+a[1]*p[1]+a[2]*p[2])/det;if(u<0||u>1)return 0;
    q[0]=a[1]*e1[2]-a[2]*e1[1];q[1]=a[2]*e1[0]-a[0]*e1[2];q[2]=a[0]*e1[1]-a[1]*e1[0];
    float w=(d[0]*q[0]+d[1]*q[1]+d[2]*q[2])/det;if(w<0||u+w>1)return 0;
    *t=(e2[0]*q[0]+e2[1]*q[1]+e2[2]*q[2])/det;return *t>=10&&*t<1500;
}
static int pick_cell(float *m,float *projection,DWORD *dims,DWORD width,DWORD height,DWORD base,int *cx,int *cy) {
    HWND win=GetForegroundWindow();DWORD pid=0;GetWindowThreadProcessId(win,&pid);
    if(pid!=GetCurrentProcessId())return 0;
    int mx=(int)word(0x717504),my=(int)word(0x717508);
    if(mx<0||my<0||mx>=(int)dims[0]||my>=(int)dims[1])return 0;
    float local[3]={(mx-(float)dims[2])/projection[0],(my-(float)dims[3])/projection[1],1};
    float o[3],d[3];
    for(int i=0;i<3;i++){o[i]=-(m[9]*m[i*3]+m[10]*m[i*3+1]+m[11]*m[i*3+2]);d[i]=local[0]*m[i*3]+local[1]*m[i*3+1]+m[i*3+2];}
    float begin=10,end=1500;
    const int axes[2]={0,2};const DWORD sizes[2]={width,height};
    for(int j=0;j<2;j++){
        int a=axes[j];float low=-(float)(sizes[j]/2)*5,high=low+sizes[j]*5;
        if(fabsf(d[a])<1e-7f){if(o[a]<low||o[a]>=high)return 0;continue;}
        float p=(low-o[a])/d[a],q=(high-o[a])/d[a];if(p>q){float z=p;p=q;q=z;}
        if(p>begin)begin=p;if(q<end)end=q;
    }
    if(begin>=end)return 0;
    float t=begin+.001f;
    for(int step=0;step<2048&&t<end;step++){
        float x=o[0]+d[0]*t,z=o[2]+d[2]*t;
        int ix=(int)floorf(x/5)+(int)(width/2),iy=(int)floorf(z/5)+(int)(height/2);
        if(ix<0||iy<0||ix>=(int)width||iy>=(int)height)return 0;
        float left=(ix-(int)(width/2))*5.0f,bottom=(iy-(int)(height/2))*5.0f;
        float h[4];
        if(copy_memory(base+20u*(ix+iy*width),h,16)){
            float quad[4][3]={{left,h[0],bottom},{left+5,h[1],bottom},{left,h[2],bottom+5},{left+5,h[3],bottom+5}};
            const int indices[2][3]={{0,1,2},{2,1,3}};
            for(int j=0;j<2;j++){float v[3][3],hit;for(int k=0;k<3;k++)memcpy(v[k],quad[indices[j][k]],12);
                if(triangle_hit(o,d,v,&hit)){*cx=ix;*cy=iy;return 1;}}
        }
        float tx=fabsf(d[0])<1e-7f?1e9f:((d[0]>0?left+5:left)-o[0])/d[0];
        float ty=fabsf(d[2])<1e-7f?1e9f:((d[2]>0?bottom+5:bottom)-o[2])/d[2];
        t=fminf(tx,ty)+.001f;
    }
    return 0;
}
static Vertex mix(Vertex a,Vertex b,float f,DWORD color){
    Vertex v={a.x+(b.x-a.x)*f,a.y+(b.y-a.y)*f,a.z+(b.z-a.z)*f,a.rhw+(b.rhw-a.rhw)*f,color};return v;
}
static void draw_cells(IDirect3DDevice7 *device) {
    Shared *s=shared;
    if(!s || !s->enabled || GetTickCount()-s->last_feed>2500 || s->count>CAP) return;
    LONG seq=s->sequence;
    if(seq&1) return;
    DWORD count=s->count,preview_count=s->preview_count;
    if(preview_count>256)return;
    memcpy(previews,s->previews,preview_count*sizeof(Preview));
    char expected[40]; memcpy(expected,s->map_name,40); expected[39]=0;
    memcpy(cells,s->cells,count*sizeof(Cell)); MemoryBarrier();
    if(seq!=s->sequence) { s->drawn=0; return; }
    DWORD mgr=s->mode_manager,mode=word(mgr+4),ren=word(s->renderer_global);
    if(word(mgr+88)!=1 || !mode || !ren) return;
    char map[40];
    if(!copy_memory(mgr+8,map,40)) return;
    map[39]=0; char *suffix=strrchr(map,'.'); if(suffix) *suffix=0;
    if(!expected[0] || _stricmp(expected,map)) return;
    DWORD world=word(mode+0xb4),view=word(mode+0xb8),attr=word(world+0x40);
    if(!world || !view || !attr || word(ren+0x7c)!=(DWORD)(uintptr_t)device) return;
    DWORD width=word(attr+0x110),height=word(attr+0x114),zoom=word(attr+0x118),base=word(attr+0x120);
    if(width<1 || width>1024 || height<1 || height>1024 || zoom!=5 || !base) return;
    float matrix[12],projection[7]; DWORD dims[4];
    if(!copy_memory(view+0x98,matrix,sizeof(matrix)) || !finite_matrix(matrix)
       || !copy_memory(ren,projection,sizeof(projection)) || !copy_memory(ren+0x24,dims,sizeof(dims))) return;
    if(!isfinite(projection[0]) || !isfinite(projection[1]) || projection[0]<10 || projection[0]>50000
       || projection[1]<10 || projection[1]>50000 || dims[0]<100 || dims[0]>16000 || dims[1]<100 || dims[1]>16000) return;
    s->selected_id=0;
    if(s->selection_preview && word(mode+0x3b4)==1){
        DWORD identity=word(mode+0x3b8);int px,py;
        for(DWORD i=0;i<preview_count;i++)if(previews[i].skill_id==identity&&previews[i].radius<=15){
            Preview p=previews[i];
            if(pick_cell(matrix,projection,dims,width,height,base,&px,&py)){
                s->selected_id=identity;
                for(int dx=-(int)p.radius;dx<=(int)p.radius;dx++)for(int dy=-(int)p.radius;dy<=(int)p.radius;dy++){
                    if(p.shape==0&&(dx||dy))continue;
                    if(p.shape==2&&abs(dx)+abs(dy)>(int)p.radius)continue;
                    if(p.shape==3&&dx&&dy)continue;
                    if(p.shape==4&&abs(dx)==(int)p.radius&&abs(dy)==(int)p.radius)continue;
                    if(count<DRAW_CAP)cells[count++]=(Cell){px+dx,py+dy,p.fill,p.outline,p.symbol};
                }
            }
            break;
        }
    }
    DWORD accepted=0,fill_vertices=0,line_vertices=0;
    const int tri[6]={0,1,2,2,1,3},edges[8]={0,1,1,3,3,2,2,0};
    for(DWORD i=0;i<count;i++) {
        int cx=cells[i].x,cy=cells[i].y;
        if(cx<0 || cy<0 || cx>=(int)width || cy>=(int)height) continue;
        float heights[4];
        if(!copy_memory(base+20u*(cx+cy*width),heights,16)) continue;
        float x=((float)cx-(float)(width/2))*5.0f+2.5f;
        float z=((float)cy-(float)(height/2))*5.0f+2.5f;
        Vertex quad[4]; int good=1;
        for(int j=0;j<4;j++) {
            if(!isfinite(heights[j]) || fabsf(heights[j])>100000) { good=0;break; }
            if(!project(x+(j&1?2.45f:-2.45f),heights[j],z+(j&2?2.45f:-2.45f),matrix,
                        projection[0],projection[1],(float)dims[2],(float)dims[3],&quad[j])) {good=0;break;}
        }
        if(!good) continue;
        DWORD fill=cells[i].fill,outline=cells[i].outline,symbol=cells[i].symbol;
        if(symbol==0)for(int j=0;j<6;j++){fills[fill_vertices]=quad[tri[j]];fills[fill_vertices++].color=fill;}
        if(symbol<=1)for(int j=0;j<8;j++){lines[line_vertices]=quad[edges[j]];lines[line_vertices++].color=outline;}
        else {
            Vertex mid[4]={mix(quad[0],quad[1],.5f,outline),mix(quad[1],quad[3],.5f,outline),mix(quad[3],quad[2],.5f,outline),mix(quad[2],quad[0],.5f,outline)};
            if(symbol==2){lines[line_vertices++]=mid[0];lines[line_vertices++]=mid[2];lines[line_vertices++]=mid[1];lines[line_vertices++]=mid[3];}
            if(symbol==3){for(int j=0;j<4;j++){const int k[4]={0,3,1,2};lines[line_vertices]=quad[k[j]];lines[line_vertices++].color=outline;}}
            if(symbol==4)for(int j=0;j<4;j++){lines[line_vertices++]=mid[j];lines[line_vertices++]=mid[(j+1)%4];}
            if(symbol==5){Vertex a=mix(mid[3],mid[1],.4f,fill),b=mix(mid[3],mid[1],.6f,fill);lines[line_vertices++]=a;lines[line_vertices++]=b;}
        }
        accepted++;
    }
    if(!accepted) {s->drawn=0;return;}
    DWORD state=0;
    if(FAILED(IDirect3DDevice7_CreateStateBlock(device,D3DSBT_ALL,&state))) {s->error=5;return;}
    IDirect3DDevice7_SetTexture(device,0,NULL);
    IDirect3DDevice7_SetTexture(device,1,NULL);
    IDirect3DDevice7_SetTextureStageState(device,0,D3DTSS_COLOROP,D3DTOP_SELECTARG1);
    IDirect3DDevice7_SetTextureStageState(device,0,D3DTSS_COLORARG1,D3DTA_DIFFUSE);
    IDirect3DDevice7_SetTextureStageState(device,0,D3DTSS_ALPHAOP,D3DTOP_SELECTARG1);
    IDirect3DDevice7_SetTextureStageState(device,0,D3DTSS_ALPHAARG1,D3DTA_DIFFUSE);
    IDirect3DDevice7_SetTextureStageState(device,1,D3DTSS_COLOROP,D3DTOP_DISABLE);
    IDirect3DDevice7_SetRenderState(device,D3DRENDERSTATE_ZENABLE,D3DZB_TRUE);
    IDirect3DDevice7_SetRenderState(device,D3DRENDERSTATE_ZWRITEENABLE,FALSE);
    IDirect3DDevice7_SetRenderState(device,D3DRENDERSTATE_ZBIAS,8);
    IDirect3DDevice7_SetRenderState(device,D3DRENDERSTATE_ZFUNC,D3DCMP_LESSEQUAL);
    IDirect3DDevice7_SetRenderState(device,D3DRENDERSTATE_FOGENABLE,FALSE);
    IDirect3DDevice7_SetRenderState(device,D3DRENDERSTATE_LIGHTING,FALSE);
    IDirect3DDevice7_SetRenderState(device,D3DRENDERSTATE_SPECULARENABLE,FALSE);
    IDirect3DDevice7_SetRenderState(device,D3DRENDERSTATE_CULLMODE,D3DCULL_NONE);
    IDirect3DDevice7_SetRenderState(device,D3DRENDERSTATE_FILLMODE,D3DFILL_SOLID);
    IDirect3DDevice7_SetRenderState(device,D3DRENDERSTATE_ALPHATESTENABLE,FALSE);
    IDirect3DDevice7_SetRenderState(device,D3DRENDERSTATE_ALPHABLENDENABLE,TRUE);
    IDirect3DDevice7_SetRenderState(device,D3DRENDERSTATE_SRCBLEND,D3DBLEND_SRCALPHA);
    IDirect3DDevice7_SetRenderState(device,D3DRENDERSTATE_DESTBLEND,D3DBLEND_INVSRCALPHA);
    HRESULT result=S_OK;
    if(fill_vertices)result=IDirect3DDevice7_DrawPrimitive(device,D3DPT_TRIANGLELIST,D3DFVF_XYZRHW|D3DFVF_DIFFUSE,fills,fill_vertices,0);
    if(line_vertices)IDirect3DDevice7_DrawPrimitive(device,D3DPT_LINELIST,D3DFVF_XYZRHW|D3DFVF_DIFFUSE,lines,line_vertices,0);
    IDirect3DDevice7_ApplyStateBlock(device,state);
    IDirect3DDevice7_DeleteStateBlock(device,state);
    s->drawn=SUCCEEDED(result)?(LONG)accepted:0;
    s->error=SUCCEEDED(result)?0:6;
}
static HRESULT WINAPI intercepted_state(IDirect3DDevice7 *device,D3DRENDERSTATETYPE type,DWORD value) {
    SetState original=NULL;
    for(LONG i=0;i<binding_count;i++) if(bindings[i].table==device->lpVtbl) {original=bindings[i].original;break;}
    if(!original) return E_FAIL;
    if(type==D3DRENDERSTATE_ZENABLE && value==FALSE && InterlockedCompareExchange(&in_draw,1,0)==0) {
        if(shared) { shared->attached=1;shared->frames++;shared->status=3; }
        draw_cells(device);
        InterlockedExchange(&in_draw,0);
    }
    return original(device,type,value);
}
static DWORD WINAPI worker(void *unused) {
    char name[100]; snprintf(name,sizeof(name),"Local\\NroRcx1_%lu_" RCX_BUILD_ID,GetCurrentProcessId());
    HANDLE mapping=OpenFileMappingA(FILE_MAP_ALL_ACCESS,FALSE,name);
    if(!mapping) return 1;
    shared=(Shared*)MapViewOfFile(mapping,FILE_MAP_ALL_ACCESS,0,0,sizeof(Shared));
    if(!shared || shared->magic!=MAGIC || shared->version!=2 || shared->pid!=GetCurrentProcessId()) return 2;
    for(;;) {
        if(shared->enabled && GetTickCount()-shared->last_feed<2500) {
            IDirect3DDevice7 *device=(IDirect3DDevice7*)(uintptr_t)word(word(shared->renderer_global)+0x7c);
            IDirect3DDevice7Vtbl *table=NULL;
            if(device && copy_memory((uintptr_t)device,&table,4) && table) {
                LONG found=-1;for(LONG i=0;i<binding_count;i++) if(bindings[i].table==table) found=i;
                if(found>=0 || binding_count<8) {
                    SetState original=NULL; DWORD protection;
                    if(copy_memory((uintptr_t)&table->SetRenderState,&original,4) && original
                       && original!=intercepted_state
                       && VirtualProtect(&table->SetRenderState,4,PAGE_READWRITE,&protection)) {
                        LONG i=found>=0?found:binding_count;
                        bindings[i].table=table; bindings[i].original=original; MemoryBarrier();
                        if(found<0) InterlockedIncrement(&binding_count);
                        InterlockedExchangePointer((void* volatile*)&table->SetRenderState,(void*)intercepted_state);
                        DWORD ignored;VirtualProtect(&table->SetRenderState,4,protection,&ignored);
                        shared->attached=1;shared->status=2;
                    } else if(original!=intercepted_state) shared->error=3;
                }
            }
        } else shared->drawn=0;
        Sleep(250);
    }
}
static LRESULT CALLBACK entry_hook(int code,WPARAM w,LPARAM l) {
    if(code>=0 && InterlockedCompareExchange(&started,1,0)==0) {
        HMODULE pin;
        GetModuleHandleExA(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS|GET_MODULE_HANDLE_EX_FLAG_PIN,(LPCSTR)entry_hook,&pin);
        HANDLE thread=CreateThread(NULL,0,worker,NULL,0,NULL);if(thread)CloseHandle(thread);
    }
    return CallNextHookEx(NULL,code,w,l);
}
__declspec(dllexport) void CALLBACK Run(HWND ignored,HINSTANCE instance,LPSTR command,int show) {
    HWND target=(HWND)(uintptr_t)strtoul(command,NULL,10);DWORD pid=0;
    DWORD tid=GetWindowThreadProcessId(target,&pid);if(!tid || !pid) return;
    char name[100];snprintf(name,sizeof(name),"Local\\NroRcx1_%lu_" RCX_BUILD_ID,pid);
    HANDLE mapping=OpenFileMappingA(FILE_MAP_ALL_ACCESS,FALSE,name);if(!mapping)return;
    Shared *s=(Shared*)MapViewOfFile(mapping,FILE_MAP_ALL_ACCESS,0,0,sizeof(Shared));
    if(!s || s->magic!=MAGIC || s->version!=2 || s->pid!=pid) return;
    HHOOK hook=SetWindowsHookExA(WH_GETMESSAGE,entry_hook,module,tid);
    if(!hook) {s->error=1;return;}
    PostMessageA(target,WM_NULL,0,0);
    DWORD startup=GetTickCount();
    while(IsWindow(target) && (GetTickCount()-s->last_feed<10000 || GetTickCount()-startup<5000)) Sleep(250);
    UnhookWindowsHookEx(hook);UnmapViewOfFile(s);CloseHandle(mapping);
}
BOOL WINAPI DllMain(HINSTANCE h,DWORD why,void *reserved) {
    if(why==DLL_PROCESS_ATTACH) {module=h;DisableThreadLibraryCalls(h);}
    return TRUE;
}
