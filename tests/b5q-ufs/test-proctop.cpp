// Test the production fixed-storage accounting with concurrent producers and
// snapshots, including signal exits, duplicate names and a full name table.
#include "B5qProcTop.h"
#include <cassert>
#include <cstdio>
#include <thread>
#include <vector>
#include <atomic>

static b5q_proc_top top;
static b5q_proc_row rows[B5Q_PROC_BUCKETS];
int main() {
    b5q_proc_spawn(&top);
    b5q_proc_exit(&top, "crasher", 11);
    b5q_proc_exit(&top, "crasher", 78u << 8);
    b5q_proc_exit(&top, "worker", 0);
    auto w = b5q_proc_snapshot(&top, rows);
    assert(w.spawns == 1 && w.exits == 3 && !w.overflow && w.rows == 2);
    assert(b5q_proc_equal(rows[0].name, "crasher") && rows[0].count == 2 && rows[0].status == 78u << 8);
    w = b5q_proc_snapshot(&top, rows);
    assert(!w.spawns && !w.exits && !w.rows);
    b5q_proc_exit(&top, "sigbus", 10);
    w = b5q_proc_snapshot(&top, rows);
    assert(w.rows == 1 && rows[0].status == 10);

    constexpr unsigned producers = 8, perThread = 20000;
    std::atomic<unsigned> done{0};
    std::vector<std::thread> threads;
    for (unsigned i = 0; i < producers; ++i) threads.emplace_back([&] {
        for (unsigned j = 0; j < perThread; ++j) {
            b5q_proc_spawn(&top);
            b5q_proc_exit(&top, j % 2 ? "same-service" : "other-service", j % 2 ? 6 : 0);
        }
        ++done;
    });
    uint64_t spawns = 0, exits = 0, counted = 0;
    do {
        w = b5q_proc_snapshot(&top, rows);
        spawns += w.spawns; exits += w.exits;
        assert(!w.overflow);
        for (unsigned j = 0; j < w.rows; ++j) counted += rows[j].count;
    } while (done.load() != producers);
    for (auto &t : threads) t.join();
    w = b5q_proc_snapshot(&top, rows);
    spawns += w.spawns; exits += w.exits;
    for (unsigned j = 0; j < w.rows; ++j) counted += rows[j].count;
    assert(spawns == producers * perThread && exits == spawns && counted == exits);

    for (unsigned i = 0; i < B5Q_PROC_BUCKETS + 50; ++i) {
        char name[64]; snprintf(name, sizeof(name), "service-%u", i);
        b5q_proc_exit(&top, name, 0);
    }
    w = b5q_proc_snapshot(&top, rows);
    counted = w.overflow;
    for (unsigned j = 0; j < w.rows; ++j) counted += rows[j].count;
    assert(w.exits == B5Q_PROC_BUCKETS + 50 && counted == w.exits && w.overflow >= 50);
    assert(w.rows + w.overflow == w.exits);
    puts("PASS: production counters, wait-status, reset, 160000 concurrent exits/snapshots, full-table explicit overflow");
}
