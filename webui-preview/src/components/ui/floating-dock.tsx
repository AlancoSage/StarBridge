import { useMotionPreference } from "@/components/MotionPreference";
// Adapted from linux-do/cdk; added accessible names and active-page state. MIT license in third-party/.
/**
 * Note: Use position fixed according to your needs
 * Desktop navbar supports horizontal and vertical layouts.
 * Mobile navbar is better positioned at bottom right.
 **/

import { cn } from "@/lib/utils";
import { IconLayoutNavbarCollapse } from "@tabler/icons-react";
import {
  AnimatePresence,
  type MotionValue,
  motion,
  useMotionValue,
  useSpring,
  useTransform,
} from "motion/react";

import { useRef, useState, memo, useCallback } from "react";

export const FloatingDock = ({
  items,
  desktopClassName,
  mobileClassName,
  mobileButtonClassName,
  desktopOrientation = "horizontal",
}: {
  items: {
    title: string;
    icon: React.ReactNode;
    href?: string;
    onClick?: () => void;
    tooltip?: string;
    customComponent?: React.ReactNode;
    external?: boolean;
    active?: boolean;
  }[];
  desktopClassName?: string;
  mobileClassName?: string;
  mobileButtonClassName?: string;
  desktopOrientation?: "horizontal" | "vertical";
}) => {
  return (
    <>
      <FloatingDockDesktop
        items={items}
        className={desktopClassName}
        orientation={desktopOrientation}
      />
      <FloatingDockMobile
        items={items}
        className={mobileClassName}
        buttonClassName={mobileButtonClassName}
      />
    </>
  );
};

const FloatingDockMobile = memo(
  ({
    items,
    className,
    buttonClassName,
  }: {
    items: {
      title: string;
      icon: React.ReactNode;
      href?: string;
      onClick?: () => void;
      tooltip?: string;
      customComponent?: React.ReactNode;
      external?: boolean;
      active?: boolean;
    }[];
    className?: string;
    buttonClassName?: string;
  }) => {
    const [open, setOpen] = useState(false);
    const { reduced: reduceMotion } = useMotionPreference();

    const toggleOpen = useCallback(() => {
      setOpen((prev) => !prev);
    }, []);

    return (
      <div className={cn("relative block md:hidden", className)}>
        <AnimatePresence>
          {open && (
            <motion.div
              layoutId={reduceMotion ? undefined : "nav"}
              className="absolute inset-x-0 bottom-full mb-2 flex flex-col gap-1"
            >
              {items.map((item, idx) => {
                if (item.title === "divider") {
                  return null; // Mobile版本不显示分隔符
                }
                return (
                  <motion.div
                    key={item.title}
                    initial={{ opacity: 0, y: reduceMotion ? 0 : 10 }}
                    animate={{
                      opacity: 1,
                      y: 0,
                    }}
                    exit={{
                      opacity: 0,
                      y: reduceMotion ? 0 : 10,
                      transition: reduceMotion
                        ? { duration: 0, delay: 0 }
                        : { delay: idx * 0.04 },
                    }}
                    transition={
                      reduceMotion
                        ? { duration: 0, delay: 0 }
                        : {
                            type: "spring",
                            stiffness: 380,
                            damping: 26,
                            delay: (items.length - 1 - idx) * 0.04,
                          }
                    }
                  >
                    {item.customComponent ? (
                      <div
                        key={item.title}
                        className={cn(
                          "flex h-8 w-8 items-center justify-center rounded-full bg-gray-50 dark:bg-neutral-900",
                          buttonClassName,
                        )}
                      >
                        {item.customComponent}
                      </div>
                    ) : item.href ? (
                      <a
                        href={item.href}
                        onClick={() => {
                          item.onClick?.();
                          setOpen(false);
                        }}
                        aria-label={item.title}
                        aria-current={item.active ? "page" : undefined}
                        key={item.title}
                        className={cn(
                          "flex h-8 w-8 items-center justify-center rounded-full bg-gray-50 dark:bg-neutral-900",
                          buttonClassName,
                        )}
                        {...(item.external || item.href.startsWith("https://")
                          ? { target: "_blank", rel: "noopener noreferrer" }
                          : {})}
                      >
                        <div className="flex items-center justify-center">
                          {item.icon}
                        </div>
                      </a>
                    ) : (
                      <button
                        onClick={() => {
                          item.onClick?.();
                          setOpen(false);
                        }}
                        aria-label={item.title}
                        aria-current={item.active ? "page" : undefined}
                        key={item.title}
                        className={cn(
                          "flex h-8 w-8 items-center justify-center rounded-full bg-gray-50 dark:bg-neutral-900",
                          buttonClassName,
                        )}
                      >
                        <div className="flex items-center justify-center">
                          {item.icon}
                        </div>
                      </button>
                    )}
                  </motion.div>
                );
              })}
            </motion.div>
          )}
        </AnimatePresence>
        <button
          onClick={toggleOpen}
          aria-label={open ? "关闭快捷导航" : "打开快捷导航"}
          aria-expanded={open}
          className={cn(
            "flex h-8 w-8 items-center justify-center rounded-full bg-gray-50 dark:bg-neutral-800",
            buttonClassName,
          )}
        >
          <motion.div
            animate={{ rotate: open && !reduceMotion ? 180 : 0 }}
            transition={{ duration: reduceMotion ? 0 : 0.3, ease: "easeInOut" }}
          >
            <IconLayoutNavbarCollapse className="h-4 w-4 text-neutral-500 dark:text-neutral-400" />
          </motion.div>
        </button>
      </div>
    );
  },
);

FloatingDockMobile.displayName = "FloatingDockMobile";

const FloatingDockDesktop = memo(
  ({
    items,
    className,
    orientation,
  }: {
    items: {
      title: string;
      icon: React.ReactNode;
      href?: string;
      onClick?: () => void;
      tooltip?: string;
      customComponent?: React.ReactNode;
      external?: boolean;
      active?: boolean;
    }[];
    className?: string;
    orientation: "horizontal" | "vertical";
  }) => {
    const mousePosition = useMotionValue(Infinity);
    const vertical = orientation === "vertical";

    const handleMouseMove = useCallback(
      (e: React.MouseEvent) => {
        // getBoundingClientRect uses viewport coordinates, including after scrolling.
        mousePosition.set(vertical ? e.clientY : e.clientX);
      },
      [mousePosition, vertical],
    );

    const handleMouseLeave = useCallback(() => {
      mousePosition.set(Infinity);
    }, [mousePosition]);

    return (
      <motion.div
        onMouseMove={handleMouseMove}
        onMouseLeave={handleMouseLeave}
        data-slot="dock-desktop"
        data-orientation={orientation}
        className={cn(
          "mx-auto hidden gap-2 rounded-xl bg-gray-50 md:flex dark:bg-neutral-900",
          vertical ? "flex-col items-center p-2" : "items-end px-2 pb-2",
          className,
        )}
      >
        {(() => {
          const dividerIndex = items.findIndex(
            (item) => item.title === "divider",
          );
          const firstRow =
            dividerIndex === -1 ? items : items.slice(0, dividerIndex);
          const secondRow =
            dividerIndex !== -1 ? items.slice(dividerIndex + 1) : [];

          return (
            <>
              <div
                data-slot="dock-group"
                className={cn(
                  "flex gap-2",
                  vertical ? "flex-col items-center" : "items-end",
                )}
              >
                {firstRow.map((item) => (
                  <IconContainer
                    mousePosition={mousePosition}
                    orientation={orientation}
                    key={item.title}
                    {...item}
                  />
                ))}
              </div>
              {dividerIndex !== -1 && (
                <div
                  data-slot="dock-divider"
                  className={cn(
                    "flex items-center justify-center self-stretch",
                    vertical ? "mx-2 my-1 py-1" : "mx-1 mt-3 px-1",
                  )}
                >
                  <div
                    className={cn(
                      "bg-border",
                      vertical ? "h-px w-full" : "h-full w-px",
                    )}
                  />
                </div>
              )}
              {secondRow.length > 0 && (
                <div
                  data-slot="dock-group"
                  className={cn(
                    "flex gap-2",
                    vertical ? "flex-col items-center" : "items-end",
                  )}
                >
                  {secondRow.map((item) => (
                    <IconContainer
                      mousePosition={mousePosition}
                      orientation={orientation}
                      key={item.title}
                      {...item}
                    />
                  ))}
                </div>
              )}
            </>
          );
        })()}
      </motion.div>
    );
  },
);

FloatingDockDesktop.displayName = "FloatingDockDesktop";

const IconContainer = memo(
  ({
    mousePosition,
    orientation,
    title,
    icon,
    href,
    onClick,
    tooltip,
    customComponent,
    external,
    active,
  }: {
    mousePosition: MotionValue;
    orientation: "horizontal" | "vertical";
    title: string;
    icon: React.ReactNode;
    href?: string;
    onClick?: () => void;
    tooltip?: string;
    customComponent?: React.ReactNode;
    external?: boolean;
    active?: boolean;
  }) => {
    const ref = useRef<HTMLDivElement>(null);
    const { reduced: reduceMotion } = useMotionPreference();
    const focusSize = useMotionValue(40);
    const vertical = orientation === "vertical";

    const distance = useTransform(mousePosition, (val) => {
      const bounds = ref.current?.getBoundingClientRect();
      if (!bounds) return Infinity;

      return vertical
        ? val - bounds.y - bounds.height / 2
        : val - bounds.x - bounds.width / 2;
    });

    const pointerSize = useTransform(distance, [-150, 0, 150], [40, 70, 40]);
    const targetSize = useTransform(() =>
      Math.max(pointerSize.get(), focusSize.get()),
    );
    const size = useSpring(targetSize, {
      mass: 0.25,
      stiffness: 260,
      damping: 19,
    });
    const iconSize = useTransform(size, [40, 70], [20, 35]);

    const [hovered, setHovered] = useState(false);
    const [focused, setFocused] = useState(false);

    const handleMouseEnter = useCallback(() => {
      setHovered(true);
    }, []);

    const handleMouseLeave = useCallback(() => {
      setHovered(false);
    }, []);

    const Element = customComponent ? "div" : href ? "a" : "button";
    const elementProps = customComponent
      ? {}
      : href
        ? {
            href,
            onClick,
            ...(external || href.startsWith("https://")
              ? { target: "_blank", rel: "noopener noreferrer" }
              : {}),
          }
        : { onClick };

    return (
      <Element
        {...elementProps}
        aria-label={title}
        aria-current={active ? "page" : undefined}
        onFocus={() => {
          setFocused(true);
          focusSize.set(64);
        }}
        onBlur={() => {
          setFocused(false);
          focusSize.set(40);
        }}
        className="outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-4"
      >
        <motion.div
          ref={ref}
          style={{
            width: reduceMotion ? 40 : size,
            height: reduceMotion ? 40 : size,
          }}
          data-dock-icon={title}
          onMouseEnter={handleMouseEnter}
          onMouseLeave={handleMouseLeave}
          className="relative flex aspect-square items-center justify-center rounded-full bg-gray-200 cursor-pointer dark:bg-neutral-800"
        >
          <AnimatePresence>
            {(hovered || focused) && (
              <motion.div
                data-slot="dock-tooltip"
                initial={
                  vertical
                    ? { opacity: 0, x: reduceMotion ? 0 : -10, y: "-50%" }
                    : { opacity: 0, y: reduceMotion ? 0 : 10, x: "-50%" }
                }
                animate={
                  vertical
                    ? { opacity: 1, x: 0, y: "-50%" }
                    : { opacity: 1, y: 0, x: "-50%" }
                }
                exit={
                  vertical
                    ? { opacity: 0, x: reduceMotion ? 0 : -2, y: "-50%" }
                    : { opacity: 0, y: reduceMotion ? 0 : 2, x: "-50%" }
                }
                transition={{ duration: reduceMotion ? 0 : 0.16 }}
                className={cn(
                  "pointer-events-none absolute z-10 w-fit rounded-md border border-gray-200 bg-gray-100 px-2 py-0.5 text-xs whitespace-pre text-neutral-700 dark:border-neutral-900 dark:bg-neutral-800 dark:text-white",
                  vertical ? "top-1/2 left-full ml-3" : "-top-8 left-1/2",
                )}
              >
                {tooltip || title}
              </motion.div>
            )}
          </AnimatePresence>
          <motion.div
            data-dock-glyph
            style={{
              width: reduceMotion ? 20 : iconSize,
              height: reduceMotion ? 20 : iconSize,
            }}
            className="flex items-center justify-center"
          >
            {customComponent || icon}
          </motion.div>
        </motion.div>
      </Element>
    );
  },
);

IconContainer.displayName = "IconContainer";
