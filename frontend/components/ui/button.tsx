import type {ButtonHTMLAttributes} from "react";
import {clsx} from "clsx";

type Props = ButtonHTMLAttributes<HTMLButtonElement> & {variant?: "primary" | "secondary" | "danger" | "ghost"};

export function Button({className, variant = "secondary", ...props}: Props) {
  return <button className={clsx("button", `button-${variant}`, className)} {...props} />;
}
