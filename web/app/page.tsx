import { NewProject } from "@/components/clipai/new-project";
import { ProjectList } from "@/components/clipai/project-list";

export default function Home() {
  return (
    <div className="pt-8">
      <NewProject />
      <ProjectList />
    </div>
  );
}
