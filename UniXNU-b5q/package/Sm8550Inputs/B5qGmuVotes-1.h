/* Generated from b5q Samsung DT and pinned shared A740 catalog. */
#include <stdint.h>
#define SHENG_GMU_VOTES_CHIP_ID 0x43050a01u
typedef struct {uint64_t hz;uint32_t level,kbps,acd_present,acd;} ShengGmuOpp;
#define SHENG_GPU_OPPS 10u
static const ShengGmuOpp sheng_gpu_opps[]={
{0,0,0,0,0},
{124800000,52,2136718,0,0},
{220000000,52,2136718,1,3224330237},
{295000000,56,6074218,1,3761070077},
{348000000,60,6074218,1,3760939005},
{401000000,64,6074218,1,3224002557},
{475000000,80,6074218,1,3760742397},
{550000000,128,6074218,1,3760742397},
{615000000,144,10687500,1,2821677053},
{680000000,192,16500000,1,2284740605},
};
#define SHENG_GMU_OPPS 3u
static const ShengGmuOpp sheng_gmu_opps[]={
{0,0,0,0,0},
{220000000,64,0,0,0},
{550000000,128,0,0,0},
};
#define SHENG_GPU_BANDWIDTHS 5u
static const uint32_t sheng_gpu_bandwidths[]={0,2136718,6074218,10687500,16500000};
static const AdrenoHfiBcm sheng_bcm_policy[3]={
{.address=0,.unit=0,.width=0,.buswidth=16,.vcd=0,.fixed=0,.perfmode=0,.perfmode_kbps=0},
{.address=0,.unit=0,.width=0,.buswidth=4,.vcd=0,.fixed=0,.perfmode=0,.perfmode_kbps=0},
{.address=0,.unit=0,.width=0,.buswidth=0,.vcd=0,.fixed=1,.perfmode=8,.perfmode_kbps=16500000},
};
