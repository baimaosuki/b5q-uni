/* SPDX-License-Identifier: BSD-2-Clause-Patent */
#ifndef B5Q_BT_FIRMWARE_NAME_H
#define B5Q_BT_FIRMWARE_NAME_H
#include <stdbool.h>
#include <stddef.h>
#include <string.h>
static inline bool b5q_bt_hex(char c){return (c>='0'&&c<='9')||(c>='a'&&c<='f');}
static inline bool b5q_bt_firmware_name(const char *name) {
    if(!name || strncmp(name,"qca/",4))return false;
    const char *p=name+4;
    if(!strncmp(p,"wcn",3))p+=3;
    if(!strncmp(p,"hpbtfw",6))return strlen(p)==12 && b5q_bt_hex(p[6]) && b5q_bt_hex(p[7]) && !strcmp(p+8,".tlv");
    if(strncmp(p,"hpnv",4) || strlen(p)<10 || !b5q_bt_hex(p[4]) || !b5q_bt_hex(p[5]))return false;
    p+=6;if(*p=='g')p++;
    if(!strcmp(p,".bin"))return true;
    if(p[0]!='.' || p[1]!='b')return false;
    p+=2;size_t n=strlen(p);if(n<2 || n>4)return false;
    for(size_t i=0;i<n;i++)if(!b5q_bt_hex(p[i]))return false;
    return true;
}
#endif
