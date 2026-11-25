/* SPDX-License-Identifier: BSD-2-Clause-Patent */
#ifndef B5Q_AOSS_QMP_LOCK_H
#define B5Q_AOSS_QMP_LOCK_H
extern "C" bool b5q_aoss_qmp_lock(void);
extern "C" void b5q_aoss_qmp_unlock(void);
// One AOSS mailbox, shared by WCN and ADSP. Never holds the RPMh mutex.
class B5qAossQmpLock {
    bool held;
public:
    B5qAossQmpLock():held(b5q_aoss_qmp_lock()) {}
    ~B5qAossQmpLock(){if(held)b5q_aoss_qmp_unlock();}
    bool ready()const{return held;}
    B5qAossQmpLock(const B5qAossQmpLock&)=delete;
    B5qAossQmpLock& operator=(const B5qAossQmpLock&)=delete;
};
#endif
