/*
 * Minimal Firefly-RK3399 direct Linux boot machine.
 * SPDX-License-Identifier: GPL-2.0-or-later
 */
#include "qemu/osdep.h"
#include "qapi/error.h"
#include "qobject/qlist.h"
#include "qemu/error-report.h"
#include "qemu/units.h"
#include "hw/arm/boot.h"
#include "hw/arm/machines-qom.h"
#include "hw/boards.h"
#include "hw/char/serial-mm.h"
#include "hw/qdev-properties.h"
#include "hw/intc/arm_gicv3_common.h"
#include "hw/sd/sdhci.h"
#include "hw/sysbus.h"
#include "system/address-spaces.h"
#include "system/system.h"
#include "target/arm/cpu.h"
#include "target/arm/gtimer.h"

/* RK3399 peripheral addresses and SPIs from Linux rk3399-base.dtsi. */
#define RK3399_CPUS 6
#define RK3399_SPIS 192
#define RK3399_UART2 0xff1a0000
#define RK3399_UART2_SPI 100
#define RK3399_GICD 0xfee00000
#define RK3399_GICR 0xfef00000
#define RK3399_SDHCI 0xfe330000
#define RK3399_SDHCI_SPI 11

static DeviceState *firefly_gic(MemoryRegion *sysmem)
{
    DeviceState *gic = qdev_new("arm-gicv3");
    SysBusDevice *bus = SYS_BUS_DEVICE(gic);
    QList *regions = qlist_new();
    static const int timer_ppi[] = {
        [GTIMER_PHYS] = 14, [GTIMER_VIRT] = 11,
        [GTIMER_HYP] = 10, [GTIMER_SEC] = 13,
    };

    qdev_prop_set_uint32(gic, "revision", 3);
    qdev_prop_set_uint32(gic, "num-cpu", RK3399_CPUS);
    qdev_prop_set_uint32(gic, "num-irq", RK3399_SPIS + GIC_INTERNAL);
    qlist_append_int(regions, RK3399_CPUS);
    qdev_prop_set_array(gic, "redist-region-count", regions);
    object_property_set_link(OBJECT(gic), "sysmem", OBJECT(sysmem), &error_fatal);
    sysbus_realize_and_unref(bus, &error_fatal);
    sysbus_mmio_map(bus, 0, RK3399_GICD);
    sysbus_mmio_map(bus, 1, RK3399_GICR);

    for (int i = 0; i < RK3399_CPUS; i++) {
        DeviceState *cpu = DEVICE(qemu_get_cpu(i));
        int ppi_base = RK3399_SPIS + i * GIC_INTERNAL + 16;
        static const int signals[] = {
            ARM_CPU_IRQ, ARM_CPU_FIQ, ARM_CPU_VIRQ, ARM_CPU_VFIQ,
        };

        for (int j = 0; j < ARRAY_SIZE(timer_ppi); j++) {
            qdev_connect_gpio_out(cpu, j,
                                 qdev_get_gpio_in(gic, ppi_base + timer_ppi[j]));
        }
        qdev_connect_gpio_out_named(cpu, "gicv3-maintenance-interrupt", 0,
                                   qdev_get_gpio_in(gic, ppi_base + 9));
        for (int j = 0; j < ARRAY_SIZE(signals); j++) {
            sysbus_connect_irq(bus, i + RK3399_CPUS * j,
                               qdev_get_gpio_in(cpu, signals[j]));
        }
    }
    return gic;
}

static void firefly_init(MachineState *ms)
{
    static struct arm_boot_info boot = { .psci_conduit = QEMU_PSCI_CONDUIT_HVC };
    MemoryRegion *sysmem = get_system_memory();
    DeviceState *gic, *sdhci;
    SysBusDevice *bus;

    if (!ms->kernel_filename || !ms->dtb || ms->firmware) {
        error_report("firefly-rk3399 requires -kernel and -dtb (direct Linux boot)");
        exit(1);
    }
    if (ms->ram_size != 2 * GiB ||
        strcmp(ms->cpu_type, ARM_CPU_TYPE_NAME("cortex-a53"))) {
        error_report("firefly-rk3399 uses a fixed 4x A53 + 2x A72 topology and 2 GiB RAM");
        exit(1);
    }
    memory_region_add_subregion(sysmem, 0, ms->ram);
    for (int i = 0; i < RK3399_CPUS; i++) {
        Object *cpu = object_new(i < 4 ? ARM_CPU_TYPE_NAME("cortex-a53") :
                                         ARM_CPU_TYPE_NAME("cortex-a72"));

        object_property_set_int(cpu, "mp-affinity", i < 4 ? i : 0x100 + i - 4,
                                &error_fatal);
        object_property_set_int(cpu, "cntfrq", 24000000, &error_fatal);
        object_property_set_bool(cpu, "has_el3", false, &error_fatal);
        object_property_set_bool(cpu, "has_el2", false, &error_fatal);
        object_property_set_link(cpu, "memory", OBJECT(sysmem), &error_fatal);
        qdev_realize_and_unref(DEVICE(cpu), NULL, &error_fatal);
    }
    gic = firefly_gic(sysmem);
    serial_mm_init(sysmem, RK3399_UART2, 2,
                   qdev_get_gpio_in(gic, RK3399_UART2_SPI), 1500000,
                   serial_hd(0), DEVICE_LITTLE_ENDIAN);

    sdhci = qdev_new(TYPE_SYSBUS_SDHCI);
    /* SDHCI v3, 50 MHz, 3.3 V, SDMA + 8-bit bus. No modeled PHY. */
    object_property_set_uint(OBJECT(sdhci), "sd-spec-version", 3, &error_fatal);
    object_property_set_uint(OBJECT(sdhci), "capareg", 0x01443200, &error_fatal);
    bus = SYS_BUS_DEVICE(sdhci);
    sysbus_realize_and_unref(bus, &error_fatal);
    sysbus_mmio_map(bus, 0, RK3399_SDHCI);
    sysbus_connect_irq(bus, 0, qdev_get_gpio_in(gic, RK3399_SDHCI_SPI));

    boot.ram_size = ms->ram_size;
    arm_load_kernel(ARM_CPU(first_cpu), ms, &boot);
}

static void firefly_class_init(MachineClass *mc)
{
    mc->desc = "Firefly-RK3399 (experimental direct Linux boot model)";
    mc->init = firefly_init;
    mc->default_cpu_type = ARM_CPU_TYPE_NAME("cortex-a53");
    mc->min_cpus = RK3399_CPUS;
    mc->max_cpus = RK3399_CPUS;
    mc->default_cpus = RK3399_CPUS;
    mc->default_ram_size = 2 * GiB;
    mc->default_ram_id = "firefly.ram";
    mc->no_floppy = true;
    mc->no_cdrom = true;
    mc->no_parallel = true;
}

DEFINE_MACHINE_AARCH64("firefly-rk3399", firefly_class_init)
