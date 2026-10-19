type ApiHealth = {
  label: "Available" | "Unavailable";
  status: "available" | "unavailable";
};

type HealthPayload = {
  status: "ok";
  service: string;
  version: string;
};

const apiBaseUrl =
  process.env.INTERNAL_API_BASE_URL ?? "http://localhost:8000/v1";

export async function getApiHealth(): Promise<ApiHealth> {
  try {
    const response = await fetch(`${apiBaseUrl}/health/live`, {
      cache: "no-store",
      signal: AbortSignal.timeout(2_000),
    });

    if (!response.ok) {
      return { label: "Unavailable", status: "unavailable" };
    }

    const payload = (await response.json()) as HealthPayload;

    return payload.status === "ok"
      ? { label: "Available", status: "available" }
      : { label: "Unavailable", status: "unavailable" };
  } catch {
    return { label: "Unavailable", status: "unavailable" };
  }
}

