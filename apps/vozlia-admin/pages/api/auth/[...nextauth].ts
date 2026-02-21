import NextAuth, { type NextAuthOptions } from "next-auth";
import GoogleProvider from "next-auth/providers/google";

function parseAllowedEmails(value: string | undefined): string[] {
  if (!value) return [];
  return value
    .split(",")
    .map((s) => s.trim().toLowerCase())
    .filter(Boolean);
}

const allowedEmails = parseAllowedEmails(process.env.ADMIN_ALLOWED_EMAILS);

export const authOptions: NextAuthOptions = {
  providers: [
    GoogleProvider({
      clientId: process.env.GOOGLE_CLIENT_ID ?? "",
      clientSecret: process.env.GOOGLE_CLIENT_SECRET ?? "",
    }),
  ],
  secret: process.env.NEXTAUTH_SECRET,
  callbacks: {
    async signIn({ user }) {
      // If no allowlist is set, allow any Google account.
      if (allowedEmails.length === 0) return true;

      const email = (user.email ?? "").toLowerCase();
      return allowedEmails.includes(email);
    },
  },
};

export default NextAuth(authOptions);
