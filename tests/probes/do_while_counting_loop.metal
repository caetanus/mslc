// EXPECT: valid
// DISASM-ORDER: OpLoopMerge
// DISASM-ORDER: OpULessThan
// DISASM-LOOP-MERGE-REACHED: yes
kernel void do_while_counting_loop(device uint *out [[buffer(0)]], uint i [[thread_position_in_grid]])
{
    uint n = 0u;
    uint sum = 0u;
    do {
        sum = sum + n;
        n = n + 1u;
    } while (n < 10u && sum < 100u);
    out[i] = sum;
}
