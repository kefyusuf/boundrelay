import net from "node:net";

net.connect(80, "127.0.0.1");

export const unreachable = true;
