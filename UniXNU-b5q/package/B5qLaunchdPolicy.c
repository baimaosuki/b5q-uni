/* SPDX-License-Identifier: BSD-2-Clause-Patent */
#include <stddef.h>
#include "B5qLaunchdPolicyData.h"
// Replaced atomically before launchd starts, on RAM and existing UFS Data.
// Canonical board-owned override lists deliberately exclude iconservices.
int b5q_launchd_policy_blob(unsigned index,const char **name,const unsigned char **data,size_t *bytes){
 if(!name||!data||!bytes)return 0;
 if(index==0){*name="disabled.plist";*data=b5q_policy_0;*bytes=sizeof(b5q_policy_0);return 1;}
 if(index==1){*name="disabled.501.plist";*data=b5q_policy_1;*bytes=sizeof(b5q_policy_1);return 1;}
 return 0;
}
