// SPDX-License-Identifier: BSD-2-Clause-Patent
#pragma once
#include <stdint.h>
#include <stddef.h>
enum { B5Q_KTHREAD_MAX=256, B5Q_KTHREAD_TOP=5, B5Q_KTHREAD_NAME=64 };
// Shared fixed ABI with b5q-kernel-thread-stats.patch. Copy only, no pointers.
struct b5q_kthread_sample { uint64_t tid,cpu_ns; char name[B5Q_KTHREAD_NAME]; };
struct b5q_kthread_rank { struct b5q_kthread_sample sample; uint64_t delta_ms,permille; };
struct b5q_kthread_window {
 struct b5q_kthread_sample previous[B5Q_KTHREAD_MAX]; unsigned previous_count;
 struct b5q_kthread_rank top[B5Q_KTHREAD_TOP];
};
static inline void b5q_kthread_update(struct b5q_kthread_window *w,const struct b5q_kthread_sample *current,unsigned count,uint64_t elapsed_ms) {
 if(count>B5Q_KTHREAD_MAX)count=B5Q_KTHREAD_MAX;
 for(unsigned i=0;i<B5Q_KTHREAD_TOP;i++)w->top[i]=(struct b5q_kthread_rank){0};
 for(unsigned i=0;i<count;i++){
  uint64_t delta=0;
  for(unsigned j=0;j<w->previous_count;j++)if(current[i].tid==w->previous[j].tid){
   if(current[i].cpu_ns>=w->previous[j].cpu_ns)delta=(current[i].cpu_ns-w->previous[j].cpu_ns)/1000000;
   break;
  }
  struct b5q_kthread_rank row={current[i],delta,elapsed_ms?delta*1000/elapsed_ms:0};
  row.sample.name[B5Q_KTHREAD_NAME-1]=0;
  for(unsigned j=0;j<B5Q_KTHREAD_TOP;j++)if(delta>w->top[j].delta_ms){
   for(unsigned k=B5Q_KTHREAD_TOP-1;k>j;k--)w->top[k]=w->top[k-1];w->top[j]=row;break;
  }
 }
 for(unsigned i=0;i<count;i++)w->previous[i]=current[i];w->previous_count=count;
}
static inline void b5q_kthread_print(const struct b5q_kthread_window *w,void (*emit)(const char *,void *),void *context) {
 char line[224];
 for(unsigned i=0;i<B5Q_KTHREAD_TOP;i++)if(w->top[i].delta_ms){
  const struct b5q_kthread_rank *p=&w->top[i];
  snprintf(line,sizeof line,"B5qProcTop: kthread TOP%u tid=%llu name=%.63s delta_cpu_ms=%llu permille=%llu\n",i+1,
   (unsigned long long)p->sample.tid,p->sample.name[0]?p->sample.name:"unnamed",(unsigned long long)p->delta_ms,(unsigned long long)p->permille);
  emit(line,context);
 }
}
