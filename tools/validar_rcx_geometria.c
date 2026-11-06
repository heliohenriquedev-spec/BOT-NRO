/* Standalone synthetic terrain/camera check. Does not attach to or alter any game. */
#include "../nrobot/native/rcx.c"
#include <assert.h>
int main(void){
    enum {W=40,H=40};
    float *terrain=(float*)calloc(W*H,20);assert(terrain);
    DWORD dims[4]={800,600,400,300};float projection[7]={500,500};int checked=0;
    for(int slope=0;slope<2;slope++){
        for(int y=0;y<H;y++)for(int x=0;x<W;x++)for(int j=0;j<4;j++){
            float wx=(x-W/2)*5.0f+(j&1?5:0),wz=(y-H/2)*5.0f+(j&2?5:0);
            terrain[5*(x+y*W)+j]=slope?wx*.10f+wz*.05f:0;
        }
        height_base=0;
        for(int rotation=0;rotation<3;rotation++)for(int pitch=0;pitch<3;pitch++){
            float angle=rotation*.7f,c=cosf(angle),sn=sinf(angle);
            float angle2=.65f+pitch*.46f,sp=sinf(angle2),cp=cosf(angle2);
            float matrix[12]={c,-sn*sp,-sn*cp,0,cp,-sp,sn,c*sp,c*cp,0,0,150};
            for(int y=0;y<H;y++)for(int x=0;x<W;x++){
                float wx=(x-W/2)*5.0f+2.5f,wz=(y-H/2)*5.0f+2.5f;
                float wy=slope?wx*.10f+wz*.05f:0;Vertex v;
                if(!project(wx,wy,wz,matrix,500,500,400,300,&v))return 2;
                int mx=(int)roundf(v.x),my=(int)roundf(v.y),px=-1,py=-1;
                if(mx<1||mx>=799||my<1||my>=599)continue;
                if(!pick_at(mx,my,matrix,projection,dims,W,H,(DWORD)(uintptr_t)terrain,&px,&py)||px!=x||py!=y){
                    printf("FAIL slope %d rotation %d expected %d,%d got %d,%d\n",slope,rotation,x,y,px,py);return 1;
                }
                checked++;
            }
        }
    }
    if(checked<=1000)return 3;free(terrain);printf("%d projected terrain cells verified (flat, slope, 3 rotations, 3 camera inclinations).\n",checked);return 0;
}
