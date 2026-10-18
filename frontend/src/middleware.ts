import createMiddleware from "next-intl/middleware";
import { routing } from "./i18n/routing";

export default createMiddleware(routing);

export const config = {
  // Everything except API proxy, Next.js internals and static files.
  matcher: ["/((?!api|_next|geo|favicon.ico|.*\\..*).*)"],
};
