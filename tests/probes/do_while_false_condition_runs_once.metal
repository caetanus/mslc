// EXPECT: valid
// DISASM: OpLoopMerge
kernel void do_while_false_condition_runs_once(device uint *out [[buffer(0)]], uint i [[thread_position_in_grid]])
{
    uint n = 0u;
    do {
        n = n + 1u;
    } while (false);
    out[i] = n;
}
