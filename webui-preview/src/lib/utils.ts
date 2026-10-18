// Adapted from linux-do/cdk. See third-party/linux-do-cdk-LICENSE.txt.
import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}
