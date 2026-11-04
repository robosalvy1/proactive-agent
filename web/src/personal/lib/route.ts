export const PERSONAL_HOME_PATH = "/home";

export const isPersonalPath = (pathname: string) => pathname.replace(/\/+$/, "") === PERSONAL_HOME_PATH;
