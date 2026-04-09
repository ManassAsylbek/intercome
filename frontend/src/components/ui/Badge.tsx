import { cn } from "@/lib/utils";

type BadgeVariant = "green" | "red" | "yellow" | "gray" | "blue" | "purple";

const variantClasses: Record<BadgeVariant, string> = {
  green: "bg-green-100 text-green-800 border-green-200",
  red: "bg-red-100 text-red-800 border-red-200",
  yellow: "bg-yellow-100 text-yellow-800 border-yellow-200",
  gray: "bg-gray-100 text-gray-600 border-gray-200",
  blue: "bg-blue-100 text-blue-800 border-blue-200",
  purple: "bg-purple-100 text-purple-800 border-purple-200",
};

interface BadgeProps {
  variant?: BadgeVariant;
  children: React.ReactNode;
  className?: string;
}

export function Badge({ variant = "gray", children, className }: BadgeProps) {
  return (
    <span
      className={cn(
        "inline-flex items-center px-2 py-0.5 rounded text-xs font-medium border",
        variantClasses[variant],
        className,
      )}
    >
      {children}
    </span>
  );
}

export function OnlineBadge({ isOnline }: { isOnline: boolean | null }) {
  if (isOnline === null || isOnline === undefined)
    return <Badge variant="gray">Неизвестно</Badge>;
  return isOnline ? (
    <Badge variant="green">● Онлайн</Badge>
  ) : (
    <Badge variant="red">● Офлайн</Badge>
  );
}
