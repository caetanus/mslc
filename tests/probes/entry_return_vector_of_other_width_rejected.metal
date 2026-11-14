// EXPECT: error cannot be converted
// Apple rejects an int2 returned as float4 (#351); only a scalar broadcasts.
fragment float4 entry_return_vector_other_type() { return int2(1); }
