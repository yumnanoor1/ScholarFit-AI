import FormLayout01 from '../ui/form-2';

/**
 * Shared profile wizard entry point kept for existing profile-form imports.
 * The wizard owns persistence and validation through the callbacks supplied
 * by the profile page.
 */
export default function AcademicBackgroundForm(props) {
  return <FormLayout01 {...props} />;
}
