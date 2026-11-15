// Vulkan side of diffcheck: runs one mslc compute entry point on whatever ICD the
// loader selects (lavapipe: set VK_ICD_FILENAMES) and writes every buffer back.
//
// Binding model (mslc's, see sema.cpp): the kernel's device/constant buffers are not
// descriptors. Binding 0 of the entry point's set is a uniform block whose members
// are the buffers' PhysicalStorageBuffer64 addresses, in parameter order ("member"
// in the reflection). Local size comes from spec constants 0, 1, 2 (LocalSizeId).
//
// Manifest, one directive per line:
//   spv <file.spv>          entry <name>          set <descriptor set of the block>
//   local X Y Z             groups X Y Z
//   buffer <member> <bytes> <input file> <output file>
// Exit 0 on success, 2 on any Vulkan or file error (never a mismatch: this host
// compares nothing). The device name goes to stdout as "device: ...".
//
// Details taken from the audited PR #148 harness: the address block's memory is sized
// from vkGetBufferMemoryRequirements, a shader-write to host-read barrier precedes the
// read-back, and maintenance4 is enabled for LocalSizeId.
#include <vulkan/vulkan.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define CHK(x) do { VkResult r_ = (x); if (r_ != VK_SUCCESS) die("%s failed: %d", #x, (int)r_); } while (0)
#define MAXBUF 32

static void die(const char *fmt, ...) __attribute__((noreturn, format(printf, 1, 2)));
#include <stdarg.h>
static void die(const char *fmt, ...) {
    va_list ap; va_start(ap, fmt); fprintf(stderr, "vkhost: "); vfprintf(stderr, fmt, ap); fputc('\n', stderr);
    va_end(ap); exit(2);
}

static VkDevice dev;
static VkPhysicalDeviceMemoryProperties mp;

static uint32_t memType(uint32_t bits) {
    VkMemoryPropertyFlags want = VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT | VK_MEMORY_PROPERTY_HOST_COHERENT_BIT;
    for (uint32_t i = 0; i < mp.memoryTypeCount; i++)
        if ((bits & (1u << i)) && (mp.memoryTypes[i].propertyFlags & want) == want) return i;
    die("no host-visible coherent memory type");
}

typedef struct { VkBuffer buf; VkDeviceMemory mem; VkDeviceSize size; } Buf;

static Buf makeBuf(VkDeviceSize size, VkBufferUsageFlags usage, int addressable) {
    Buf b = {0};
    VkBufferCreateInfo ci = {VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO};
    ci.size = size ? size : 4; ci.usage = usage;
    CHK(vkCreateBuffer(dev, &ci, NULL, &b.buf));
    VkMemoryRequirements req;
    vkGetBufferMemoryRequirements(dev, b.buf, &req);
    VkMemoryAllocateFlagsInfo fl = {VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_FLAGS_INFO};
    fl.flags = VK_MEMORY_ALLOCATE_DEVICE_ADDRESS_BIT;
    VkMemoryAllocateInfo ai = {VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO};
    ai.pNext = addressable ? &fl : NULL;
    ai.allocationSize = req.size; ai.memoryTypeIndex = memType(req.memoryTypeBits);
    CHK(vkAllocateMemory(dev, &ai, NULL, &b.mem));
    CHK(vkBindBufferMemory(dev, b.buf, b.mem, 0));
    b.size = size;
    return b;
}

static void *slurp(const char *path, size_t *n) {
    FILE *f = fopen(path, "rb");
    if (!f) die("cannot open %s", path);
    fseek(f, 0, SEEK_END); long l = ftell(f); fseek(f, 0, SEEK_SET);
    void *p = malloc(l ? l : 1);
    if (fread(p, 1, l, f) != (size_t)l) die("short read of %s", path);
    fclose(f); *n = (size_t)l; return p;
}

int main(int argc, char **argv) {
    if (argc != 2) die("usage: vkhost manifest");
    char spv[1024] = "", entry[256] = "main", in[MAXBUF][1024], out[MAXBUF][1024];
    unsigned local[3] = {1, 1, 1}, groups[3] = {1, 1, 1}, set = 0, member[MAXBUF], nbuf = 0;
    unsigned long long bytes[MAXBUF];
    FILE *mf = fopen(argv[1], "r");
    if (!mf) die("cannot open %s", argv[1]);
    char line[4096];
    while (fgets(line, sizeof line, mf)) {
        if (sscanf(line, "spv %1023s", spv) == 1 || sscanf(line, "entry %255s", entry) == 1) continue;
        if (sscanf(line, "set %u", &set) == 1) continue;
        if (sscanf(line, "local %u %u %u", local, local + 1, local + 2) == 3) continue;
        if (sscanf(line, "groups %u %u %u", groups, groups + 1, groups + 2) == 3) continue;
        if (nbuf < MAXBUF && sscanf(line, "buffer %u %llu %1023s %1023s", &member[nbuf], &bytes[nbuf], in[nbuf], out[nbuf]) == 4) { nbuf++; continue; }
        if (line[0] != '\n') die("bad manifest line: %s", line);
    }
    fclose(mf);
    if (!spv[0]) die("manifest has no spv");
    for (unsigned i = 0; i < nbuf; i++) if (member[i] != i) die("buffers must be listed as members 0..n-1 in order");

    VkApplicationInfo app = {VK_STRUCTURE_TYPE_APPLICATION_INFO};
    app.apiVersion = VK_API_VERSION_1_3;
    VkInstanceCreateInfo ici = {VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO};
    ici.pApplicationInfo = &app;
    VkInstance inst;
    CHK(vkCreateInstance(&ici, NULL, &inst));
    VkPhysicalDevice pd; uint32_t npd = 1;
    VkResult er = vkEnumeratePhysicalDevices(inst, &npd, &pd);
    if ((er != VK_SUCCESS && er != VK_INCOMPLETE) || npd == 0) die("no Vulkan device (is VK_ICD_FILENAMES set to lavapipe?)");
    VkPhysicalDeviceProperties props;
    vkGetPhysicalDeviceProperties(pd, &props);
    printf("device: %s\n", props.deviceName);
    vkGetPhysicalDeviceMemoryProperties(pd, &mp);

    uint32_t qf = UINT32_MAX, nq = 8; VkQueueFamilyProperties qfp[8];
    vkGetPhysicalDeviceQueueFamilyProperties(pd, &nq, qfp);
    for (uint32_t i = 0; i < nq; i++) if (qfp[i].queueFlags & VK_QUEUE_COMPUTE_BIT) { qf = i; break; }
    if (qf == UINT32_MAX) die("no compute queue");

    // Enable everything the device offers: the module's capabilities (Int64, Float16,
    // 8/16-bit storage, ...) depend on the kernel, and this host does not parse them.
    VkPhysicalDeviceVulkan13Features v13 = {VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_VULKAN_1_3_FEATURES};
    VkPhysicalDeviceVulkan12Features v12 = {VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_VULKAN_1_2_FEATURES};
    VkPhysicalDeviceVulkan11Features v11 = {VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_VULKAN_1_1_FEATURES};
    VkPhysicalDeviceFeatures2 f2 = {VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_FEATURES_2};
    f2.pNext = &v11; v11.pNext = &v12; v12.pNext = &v13;
    vkGetPhysicalDeviceFeatures2(pd, &f2);
    if (!v12.bufferDeviceAddress) die("device lacks bufferDeviceAddress");
    if (!v13.maintenance4) die("device lacks maintenance4 (LocalSizeId)");
    float prio = 1.0f;
    VkDeviceQueueCreateInfo qci = {VK_STRUCTURE_TYPE_DEVICE_QUEUE_CREATE_INFO};
    qci.queueFamilyIndex = qf; qci.queueCount = 1; qci.pQueuePriorities = &prio;
    VkDeviceCreateInfo dci = {VK_STRUCTURE_TYPE_DEVICE_CREATE_INFO};
    dci.pNext = &f2; dci.queueCreateInfoCount = 1; dci.pQueueCreateInfos = &qci;
    CHK(vkCreateDevice(pd, &dci, NULL, &dev));

    Buf bufs[MAXBUF]; VkDeviceAddress addr[MAXBUF + 1];
    for (unsigned i = 0; i < nbuf; i++) {
        bufs[i] = makeBuf(bytes[i], VK_BUFFER_USAGE_STORAGE_BUFFER_BIT | VK_BUFFER_USAGE_SHADER_DEVICE_ADDRESS_BIT, 1);
        size_t n; void *data = slurp(in[i], &n);
        if (n != bytes[i]) die("%s is %zu bytes, manifest says %llu", in[i], n, bytes[i]);
        void *m; CHK(vkMapMemory(dev, bufs[i].mem, 0, VK_WHOLE_SIZE, 0, &m));
        memcpy(m, data, n); vkUnmapMemory(dev, bufs[i].mem); free(data);
        VkBufferDeviceAddressInfo ai = {VK_STRUCTURE_TYPE_BUFFER_DEVICE_ADDRESS_INFO};
        ai.buffer = bufs[i].buf;
        addr[i] = vkGetBufferDeviceAddress(dev, &ai);
        if (!addr[i]) die("device address of buffer %u is 0", i);
    }

    VkDescriptorSetLayout dsl = VK_NULL_HANDLE, layouts[8]; VkDescriptorSet dset = VK_NULL_HANDLE;
    VkPipelineLayoutCreateInfo plci = {VK_STRUCTURE_TYPE_PIPELINE_LAYOUT_CREATE_INFO};
    if (nbuf) {
        // The address block is a uniform buffer at binding 0 of `set`; earlier sets stay empty.
        Buf blk = makeBuf(8 * nbuf, VK_BUFFER_USAGE_UNIFORM_BUFFER_BIT, 0);
        void *m; CHK(vkMapMemory(dev, blk.mem, 0, VK_WHOLE_SIZE, 0, &m));
        memcpy(m, addr, 8 * nbuf); vkUnmapMemory(dev, blk.mem);
        VkDescriptorSetLayoutBinding lb = {0, VK_DESCRIPTOR_TYPE_UNIFORM_BUFFER, 1, VK_SHADER_STAGE_COMPUTE_BIT, NULL};
        VkDescriptorSetLayoutCreateInfo lci = {VK_STRUCTURE_TYPE_DESCRIPTOR_SET_LAYOUT_CREATE_INFO};
        lci.bindingCount = 1; lci.pBindings = &lb;
        CHK(vkCreateDescriptorSetLayout(dev, &lci, NULL, &dsl));
        VkDescriptorSetLayoutCreateInfo eci = {VK_STRUCTURE_TYPE_DESCRIPTOR_SET_LAYOUT_CREATE_INFO};
        VkDescriptorSetLayout empty;
        CHK(vkCreateDescriptorSetLayout(dev, &eci, NULL, &empty));
        if (set >= 8) die("descriptor set %u too large", set);
        for (unsigned s = 0; s < 8; s++) layouts[s] = s == set ? dsl : empty;
        plci.setLayoutCount = set + 1; plci.pSetLayouts = layouts;
        VkDescriptorPoolSize ps = {VK_DESCRIPTOR_TYPE_UNIFORM_BUFFER, 1};
        VkDescriptorPoolCreateInfo pci = {VK_STRUCTURE_TYPE_DESCRIPTOR_POOL_CREATE_INFO};
        pci.maxSets = 1; pci.poolSizeCount = 1; pci.pPoolSizes = &ps;
        VkDescriptorPool pool; CHK(vkCreateDescriptorPool(dev, &pci, NULL, &pool));
        VkDescriptorSetAllocateInfo dai = {VK_STRUCTURE_TYPE_DESCRIPTOR_SET_ALLOCATE_INFO};
        dai.descriptorPool = pool; dai.descriptorSetCount = 1; dai.pSetLayouts = &dsl;
        CHK(vkAllocateDescriptorSets(dev, &dai, &dset));
        VkDescriptorBufferInfo dbi = {blk.buf, 0, blk.size};
        VkWriteDescriptorSet w = {VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET};
        w.dstSet = dset; w.descriptorCount = 1; w.descriptorType = VK_DESCRIPTOR_TYPE_UNIFORM_BUFFER; w.pBufferInfo = &dbi;
        vkUpdateDescriptorSets(dev, 1, &w, 0, NULL);
    }
    VkPipelineLayout layout;
    CHK(vkCreatePipelineLayout(dev, &plci, NULL, &layout));

    size_t codeSize; uint32_t *code = slurp(spv, &codeSize);
    VkShaderModuleCreateInfo smci = {VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO};
    smci.codeSize = codeSize; smci.pCode = code;
    VkShaderModule mod; CHK(vkCreateShaderModule(dev, &smci, NULL, &mod));
    VkSpecializationMapEntry me[3] = {{0, 0, 4}, {1, 4, 4}, {2, 8, 4}};
    VkSpecializationInfo si = {3, me, sizeof local, local};
    VkComputePipelineCreateInfo pci = {VK_STRUCTURE_TYPE_COMPUTE_PIPELINE_CREATE_INFO};
    pci.stage.sType = VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO;
    pci.stage.stage = VK_SHADER_STAGE_COMPUTE_BIT; pci.stage.module = mod;
    pci.stage.pName = entry; pci.stage.pSpecializationInfo = &si; pci.layout = layout;
    VkPipeline pipe; CHK(vkCreateComputePipelines(dev, VK_NULL_HANDLE, 1, &pci, NULL, &pipe));

    VkCommandPoolCreateInfo cpi = {VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO};
    cpi.queueFamilyIndex = qf;
    VkCommandPool cp; CHK(vkCreateCommandPool(dev, &cpi, NULL, &cp));
    VkCommandBufferAllocateInfo cai = {VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO};
    cai.commandPool = cp; cai.level = VK_COMMAND_BUFFER_LEVEL_PRIMARY; cai.commandBufferCount = 1;
    VkCommandBuffer cmd; CHK(vkAllocateCommandBuffers(dev, &cai, &cmd));
    VkCommandBufferBeginInfo bi = {VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO};
    CHK(vkBeginCommandBuffer(cmd, &bi));
    vkCmdBindPipeline(cmd, VK_PIPELINE_BIND_POINT_COMPUTE, pipe);
    if (nbuf) vkCmdBindDescriptorSets(cmd, VK_PIPELINE_BIND_POINT_COMPUTE, layout, set, 1, &dset, 0, NULL);
    vkCmdDispatch(cmd, groups[0], groups[1], groups[2]);
    VkMemoryBarrier mb = {VK_STRUCTURE_TYPE_MEMORY_BARRIER};
    mb.srcAccessMask = VK_ACCESS_SHADER_WRITE_BIT; mb.dstAccessMask = VK_ACCESS_HOST_READ_BIT;
    vkCmdPipelineBarrier(cmd, VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT, VK_PIPELINE_STAGE_HOST_BIT, 0, 1, &mb, 0, NULL, 0, NULL);
    CHK(vkEndCommandBuffer(cmd));
    VkQueue q; vkGetDeviceQueue(dev, qf, 0, &q);
    VkSubmitInfo sub = {VK_STRUCTURE_TYPE_SUBMIT_INFO};
    sub.commandBufferCount = 1; sub.pCommandBuffers = &cmd;
    CHK(vkQueueSubmit(q, 1, &sub, VK_NULL_HANDLE));
    CHK(vkQueueWaitIdle(q));

    for (unsigned i = 0; i < nbuf; i++) {
        void *m; CHK(vkMapMemory(dev, bufs[i].mem, 0, VK_WHOLE_SIZE, 0, &m));
        FILE *f = fopen(out[i], "wb");
        if (!f || fwrite(m, 1, bytes[i], f) != bytes[i]) die("cannot write %s", out[i]);
        fclose(f); vkUnmapMemory(dev, bufs[i].mem);
    }
    return 0;
}
