// Metal side of diffcheck: compiles a kernel with Apple's compiler, writes Apple's own
// reflection of its buffers, and (in run mode) dispatches it and writes every buffer back.
//
// Manifest, one directive per line (same shape as vkhost's):
//   mode reflect|run          source <file.metal> | metallib <file>     entry <name>
//   std <2.4|3.0|3.1|3.2>     local X Y Z       groups X Y Z       reflection <out.json>
//   buffer <metal index> <bytes> <input file> <output file>          (run mode)
// The source is compiled with newLibraryWithSource and MTLMathModeSafe, the way Blender
// and Darling's callers do; a metallib (built by `xcrun metal`) is for sources that
// #include a local header, which an in-memory source cannot resolve.
//
// The reflection lists, per buffer: index, name, access, whether it is a pointer, the
// byte stride of one element, and every scalar leaf of the element type as {off, scalar}.
// Vectors and matrices are flattened to their components, structs and arrays are
// walked, so the driver needs no knowledge of Metal types. Arguments the harness cannot
// feed (textures, samplers, threadgroup memory, argument buffers) are listed in
// "unsupported". Exit 0 on success, 2 on any error (never a mismatch).
#import <Foundation/Foundation.h>
#import <Metal/Metal.h>
#include <string>
#include <vector>

static void die(NSString *msg) { fprintf(stderr, "metalhost: %s\n", msg.UTF8String); exit(2); }

struct Leaf { NSUInteger off; const char *scalar; };

// MTLDataType -> (scalar name, rows, columns). columns 1 is a vector, rows 1 a scalar.
static bool shape(MTLDataType t, const char **scalar, int *rows, int *cols, NSUInteger *colStride) {
#define V(S, N, T) case MTLDataType##T##N: *scalar = S; *rows = N; *cols = 1; *colStride = 0; return true;
#define SCALAR(S, T) case MTLDataType##T: *scalar = S; *rows = 1; *cols = 1; *colStride = 0; return true;
#define KIND(S, T) SCALAR(S, T) V(S, 2, T) V(S, 3, T) V(S, 4, T)
#define M(S, C, R, T) case MTLDataType##T##C##x##R: *scalar = S; *rows = R; *cols = C; *colStride = (R == 3 ? 4 : R) * (S[0] == 'h' ? 2 : 4); return true;
#define MATS(S, T) M(S, 2, 2, T) M(S, 2, 3, T) M(S, 2, 4, T) M(S, 3, 2, T) M(S, 3, 3, T) M(S, 3, 4, T) M(S, 4, 2, T) M(S, 4, 3, T) M(S, 4, 4, T)
    switch (t) {
        KIND("float", Float) KIND("half", Half) KIND("int", Int) KIND("uint", UInt) KIND("short", Short)
        KIND("ushort", UShort) KIND("char", Char) KIND("uchar", UChar) KIND("long", Long) KIND("ulong", ULong)
        KIND("bool", Bool)
        MATS("float", Float) MATS("half", Half)
        default: return false;
    }
}

static NSUInteger scalarSize(const char *s) {
    std::string n(s);
    if (n == "half" || n == "short" || n == "ushort") return 2;
    if (n == "char" || n == "uchar" || n == "bool") return 1;
    if (n == "long" || n == "ulong") return 8;
    return 4;
}

static NSMutableArray *g_unsupported;

static void addLeaves(NSMutableArray *out, NSUInteger base, MTLDataType t, MTLStructType *st, MTLArrayType *at,
                      NSString *what) {
    const char *scalar; int rows, cols; NSUInteger colStride;
    if (t == MTLDataTypeStruct && st) {
        for (MTLStructMember *m in st.members)
            addLeaves(out, base + m.offset, m.dataType, m.structType, m.arrayType, [what stringByAppendingFormat:@".%@", m.name]);
    } else if (t == MTLDataTypeArray && at) {
        for (NSUInteger i = 0; i < at.arrayLength; i++)
            addLeaves(out, base + i * at.stride, at.elementType, at.elementStructType, at.elementArrayType, what);
    } else if (shape(t, &scalar, &rows, &cols, &colStride)) {
        NSUInteger sz = scalarSize(scalar);
        for (int c = 0; c < cols; c++)
            for (int r = 0; r < rows; r++)
                [out addObject:@{@"off": @(base + c * colStride + r * sz), @"scalar": @(scalar)}];
    } else {
        [g_unsupported addObject:[NSString stringWithFormat:@"%@: data type %lu", what, (unsigned long)t]];
    }
}

int main(int argc, char **argv) {
    @autoreleasepool {
        if (argc != 2) die(@"usage: metalhost manifest");
        NSMutableDictionary *m = [NSMutableDictionary dictionary];
        NSMutableArray *bufSpecs = [NSMutableArray array];
        NSString *text = [NSString stringWithContentsOfFile:@(argv[1]) encoding:NSUTF8StringEncoding error:nil];
        if (!text) die(@"cannot read manifest");
        for (NSString *line in [text componentsSeparatedByString:@"\n"]) {
            NSArray *w = [line componentsSeparatedByString:@" "];
            if (line.length == 0) continue;
            if ([w[0] isEqual:@"buffer"] && w.count == 5) [bufSpecs addObject:w];
            else if (w.count >= 2) m[w[0]] = [w subarrayWithRange:NSMakeRange(1, w.count - 1)];
            else die([@"bad manifest line: " stringByAppendingString:line]);
        }
        BOOL run = [m[@"mode"][0] isEqual:@"run"];
        NSString *entry = m[@"entry"][0];
        if (!entry) die(@"manifest has no entry");

        id<MTLDevice> device = MTLCreateSystemDefaultDevice();
        if (!device) die(@"no Metal device");
        NSError *err = nil;
        id<MTLLibrary> lib;
        if (m[@"metallib"]) {
            lib = [device newLibraryWithURL:[NSURL fileURLWithPath:m[@"metallib"][0]] error:&err];
        } else {
            NSString *src = [NSString stringWithContentsOfFile:m[@"source"][0] encoding:NSUTF8StringEncoding error:nil];
            if (!src) die(@"cannot read the source");
            MTLCompileOptions *opts = [MTLCompileOptions new];
            opts.mathMode = MTLMathModeSafe;
            NSString *std = m[@"std"][0];
            if (std) {
                if ([std isEqual:@"2.4"]) opts.languageVersion = MTLLanguageVersion2_4;
                else if ([std isEqual:@"3.0"]) opts.languageVersion = MTLLanguageVersion3_0;
                else if ([std isEqual:@"3.1"]) opts.languageVersion = MTLLanguageVersion3_1;
                else if ([std isEqual:@"3.2"]) opts.languageVersion = MTLLanguageVersion3_2;
                else die(@"unknown std");
            }
            lib = [device newLibraryWithSource:src options:opts error:&err];
        }
        if (!lib) die([@"Apple compile failed: " stringByAppendingString:err.localizedDescription ?: @"?"]);
        id<MTLFunction> fn = [lib newFunctionWithName:entry];
        if (!fn) die(@"no such entry point in the Apple library");

        MTLComputePipelineDescriptor *pd = [MTLComputePipelineDescriptor new];
        pd.computeFunction = fn;
        MTLComputePipelineReflection *refl = nil;
        id<MTLComputePipelineState> pso = [device newComputePipelineStateWithDescriptor:pd
            options:MTLPipelineOptionBindingInfo | MTLPipelineOptionBufferTypeInfo reflection:&refl error:&err];
        if (!pso) die([@"pipeline failed: " stringByAppendingString:err.localizedDescription ?: @"?"]);

        g_unsupported = [NSMutableArray array];
        NSMutableArray *buffers = [NSMutableArray array];
        for (id<MTLBinding> b in refl.bindings) {
            if (b.type != MTLBindingTypeBuffer) {
                [g_unsupported addObject:[NSString stringWithFormat:@"%@ (index %lu, binding type %ld)", b.name,
                    (unsigned long)b.index, (long)b.type]];
                continue;
            }
            id<MTLBufferBinding> bb = (id<MTLBufferBinding>)b;
            NSMutableArray *leaves = [NSMutableArray array];
            NSUInteger stride;
            BOOL pointer = bb.bufferPointerType != nil;
            if (pointer) {
                MTLPointerType *p = bb.bufferPointerType;
                stride = p.elementIsArgumentBuffer ? 0 : p.dataSize;
                addLeaves(leaves, 0, p.elementType, p.elementStructType, p.elementArrayType, bb.name);
            } else {
                stride = bb.bufferDataSize;
                addLeaves(leaves, 0, bb.bufferDataType, bb.bufferStructType, nil, bb.name);
            }
            NSArray *access = @[@"read", @"readwrite", @"write"];
            [buffers addObject:@{@"index": @(bb.index), @"name": bb.name, @"access": access[bb.access],
                @"pointer": @(pointer), @"stride": @(stride), @"alignment": @(bb.bufferAlignment), @"leaves": leaves}];
        }
        NSDictionary *doc = @{@"device": device.name, @"buffers": buffers, @"unsupported": g_unsupported,
            @"max_threads": @(pso.maxTotalThreadsPerThreadgroup), @"execution_width": @(pso.threadExecutionWidth)};
        if (m[@"reflection"]) {
            NSData *j = [NSJSONSerialization dataWithJSONObject:doc options:NSJSONWritingSortedKeys error:nil];
            [j writeToFile:m[@"reflection"][0] atomically:YES];
        }
        if (!run) return 0;

        NSArray *lc = m[@"local"], *gc = m[@"groups"];
        if (lc.count != 3 || gc.count != 3) die(@"run mode needs local and groups");
        id<MTLCommandQueue> q = [device newCommandQueue];
        id<MTLCommandBuffer> cb = [q commandBuffer];
        id<MTLComputeCommandEncoder> enc = [cb computeCommandEncoder];
        [enc setComputePipelineState:pso];
        NSMutableArray<id<MTLBuffer>> *bufs = [NSMutableArray array];
        for (NSArray *w in bufSpecs) {
            NSUInteger idx = [w[1] integerValue], n = [w[2] integerValue];
            NSData *d = [NSData dataWithContentsOfFile:w[3]];
            if (d.length != n) die(@"input file size differs from the manifest");
            id<MTLBuffer> b = [device newBufferWithBytes:d.bytes length:n ? n : 4 options:MTLResourceStorageModeShared];
            [enc setBuffer:b offset:0 atIndex:idx];
            [bufs addObject:b];
        }
        [enc dispatchThreadgroups:MTLSizeMake([gc[0] integerValue], [gc[1] integerValue], [gc[2] integerValue])
            threadsPerThreadgroup:MTLSizeMake([lc[0] integerValue], [lc[1] integerValue], [lc[2] integerValue])];
        [enc endEncoding];
        [cb commit];
        [cb waitUntilCompleted];
        if (cb.status != MTLCommandBufferStatusCompleted) die([@"command buffer failed: " stringByAppendingString:cb.error.localizedDescription ?: @"?"]);
        for (NSUInteger i = 0; i < bufSpecs.count; i++) {
            NSUInteger n = [bufSpecs[i][2] integerValue];
            NSData *o = [NSData dataWithBytes:bufs[i].contents length:n];
            if (![o writeToFile:bufSpecs[i][4] atomically:YES]) die(@"cannot write an output file");
        }
        printf("device: %s\n", device.name.UTF8String);
    }
    return 0;
}
