import { ProjectView } from "@/components/clipai/project-view";

export default async function ProjectPage({ params }: PageProps<"/projects/[id]">) {
  const { id } = await params;
  return <ProjectView id={id} />;
}
