// Adapted from the "modern animated sign-in" block for this Vite + React app:
// - motion APIs come from framer-motion (same library as `motion/react`, already installed)
// - next/image replaced by <img>; no 'use client' needed outside Next.js
// - colours use explicit values instead of shadcn CSS variables, so nothing global changes
// - extra props: Ripple/TechOrbitDisplay class overrides, AnimatedForm submitting state,
//   field autocomplete/name, and a footer slot
import {
  memo,
  ReactNode,
  useState,
  ChangeEvent,
  FormEvent,
  useEffect,
  useRef,
  forwardRef,
} from 'react';
import {
  motion,
  useAnimation,
  useInView,
  useMotionTemplate,
  useMotionValue,
} from 'framer-motion';
import { Eye, EyeOff } from 'lucide-react';
import { cn } from '@/lib/utils';
import GoogleIcon from '@/components/auth/GoogleIcon';

// ==================== Input Component ====================

const Input = memo(
  forwardRef(function Input(
    { className, type, ...props }: React.InputHTMLAttributes<HTMLInputElement>,
    ref: React.ForwardedRef<HTMLInputElement>
  ) {
    const radius = 100; // radius of the hover glow
    const [visible, setVisible] = useState(false);

    const mouseX = useMotionValue(0);
    const mouseY = useMotionValue(0);

    function handleMouseMove({
      currentTarget,
      clientX,
      clientY,
    }: React.MouseEvent<HTMLDivElement>) {
      const { left, top } = currentTarget.getBoundingClientRect();
      mouseX.set(clientX - left);
      mouseY.set(clientY - top);
    }

    return (
      <motion.div
        style={{
          background: useMotionTemplate`
        radial-gradient(
          ${visible ? radius + 'px' : '0px'} circle at ${mouseX}px ${mouseY}px,
          var(--brand-blue-light),
          transparent 80%
        )
      `,
        }}
        onMouseMove={handleMouseMove}
        onMouseEnter={() => setVisible(true)}
        onMouseLeave={() => setVisible(false)}
        className='group/input rounded-lg p-[2px] transition duration-300'
      >
        <input
          type={type}
          className={cn(
            `shadow-input flex h-11 w-full rounded-md border-none bg-(--brand-surface) px-3 py-2 text-sm text-(--color-dark) transition duration-400 group-hover/input:shadow-none file:border-0 file:bg-transparent file:text-sm file:font-medium placeholder:text-(--color-secondary) focus-visible:ring-[2px] focus-visible:ring-(--brand-blue) focus-visible:outline-none disabled:cursor-not-allowed disabled:opacity-50`,
            className
          )}
          ref={ref}
          {...props}
        />
      </motion.div>
    );
  })
);

Input.displayName = 'Input';

// ==================== BoxReveal Component ====================

type BoxRevealProps = {
  children: ReactNode;
  width?: string;
  boxColor?: string;
  duration?: number;
  overflow?: string;
  position?: string;
  className?: string;
};

const BoxReveal = memo(function BoxReveal({
  children,
  width = 'fit-content',
  boxColor,
  duration,
  overflow = 'hidden',
  position = 'relative',
  className,
}: BoxRevealProps) {
  const mainControls = useAnimation();
  const slideControls = useAnimation();
  const ref = useRef(null);
  const isInView = useInView(ref, { once: true });

  useEffect(() => {
    if (isInView) {
      slideControls.start('visible');
      mainControls.start('visible');
    } else {
      slideControls.start('hidden');
      mainControls.start('hidden');
    }
  }, [isInView, mainControls, slideControls]);

  return (
    <section
      ref={ref}
      style={{
        position: position as 'relative' | 'absolute' | 'fixed' | 'sticky' | 'static',
        width,
        overflow,
      }}
      className={className}
    >
      <motion.div
        variants={{
          hidden: { opacity: 0, y: 75 },
          visible: { opacity: 1, y: 0 },
        }}
        initial='hidden'
        animate={mainControls}
        transition={{ duration: duration ?? 0.5, delay: 0.25 }}
      >
        {children}
      </motion.div>
      <motion.div
        variants={{ hidden: { left: 0 }, visible: { left: '100%' } }}
        initial='hidden'
        animate={slideControls}
        transition={{ duration: duration ?? 0.5, ease: 'easeIn' }}
        style={{
          position: 'absolute',
          top: 4,
          bottom: 4,
          left: 0,
          right: 0,
          zIndex: 20,
          background: boxColor ?? 'var(--brand-tint)',
          borderRadius: 4,
        }}
      />
    </section>
  );
});

// ==================== Ripple Component ====================

type RippleProps = {
  mainCircleSize?: number;
  mainCircleOpacity?: number;
  numCircles?: number;
  className?: string;
  circleClassName?: string;
};

const Ripple = memo(function Ripple({
  mainCircleSize = 210,
  mainCircleOpacity = 0.24,
  numCircles = 11,
  className = 'max-w-[50%] bg-(--brand-surface)',
  circleClassName = 'bg-(--brand-navy)/15 border-(--brand-navy)/10',
}: RippleProps) {
  return (
    <section
      aria-hidden='true'
      className={cn(
        'pointer-events-none absolute inset-0 flex items-center justify-center [mask-image:linear-gradient(to_bottom,black,transparent)]',
        className
      )}
    >
      {Array.from({ length: numCircles }, (_, i) => {
        const size = mainCircleSize + i * 70;
        const opacity = mainCircleOpacity - i * 0.03;
        const animationDelay = `${i * 0.06}s`;
        const borderStyle = i === numCircles - 1 ? 'dashed' : 'solid';

        return (
          <span
            key={i}
            className={cn('absolute animate-ripple rounded-full border motion-reduce:animate-none', circleClassName)}
            style={{
              width: `${size}px`,
              height: `${size}px`,
              opacity,
              animationDelay,
              borderStyle,
              borderWidth: '1px',
              top: '50%',
              left: '50%',
              transform: 'translate(-50%, -50%)',
            }}
          />
        );
      })}
    </section>
  );
});

// ==================== OrbitingCircles Component ====================

type OrbitingCirclesProps = {
  className?: string;
  children: ReactNode;
  reverse?: boolean;
  duration?: number;
  delay?: number;
  radius?: number;
  path?: boolean;
  pathClassName?: string;
};

const OrbitingCircles = memo(function OrbitingCircles({
  className,
  children,
  reverse = false,
  duration = 20,
  delay = 10,
  radius = 50,
  path = true,
  pathClassName = 'stroke-(--brand-navy)/10',
}: OrbitingCirclesProps) {
  return (
    <>
      {path && (
        <svg
          xmlns='http://www.w3.org/2000/svg'
          version='1.1'
          aria-hidden='true'
          className='pointer-events-none absolute inset-0 size-full'
        >
          <circle className={cn('stroke-1', pathClassName)} cx='50%' cy='50%' r={radius} fill='none' />
        </svg>
      )}
      <section
        style={
          {
            '--duration': duration,
            '--radius': radius,
            '--delay': -delay,
          } as React.CSSProperties
        }
        className={cn(
          'absolute flex size-full transform-gpu animate-orbit items-center justify-center rounded-full border bg-(--brand-navy)/10 [animation-delay:calc(var(--delay)*1000ms)] motion-reduce:animate-none',
          { '[animation-direction:reverse]': reverse },
          className
        )}
      >
        {children}
      </section>
    </>
  );
});

// ==================== TechOrbitDisplay Component ====================

type IconConfig = {
  className?: string;
  duration?: number;
  delay?: number;
  radius?: number;
  path?: boolean;
  reverse?: boolean;
  component: () => React.ReactNode;
};

type TechnologyOrbitDisplayProps = {
  iconsArray: IconConfig[];
  text?: string;
  textClassName?: string;
  pathClassName?: string;
  /** Rendered in the centre instead of `text` (e.g. a logo) */
  centerContent?: ReactNode;
};

const TechOrbitDisplay = memo(function TechOrbitDisplay({
  iconsArray,
  text = 'Animated Login',
  textClassName = 'bg-gradient-to-b from-(--brand-navy) to-(--brand-blue)/80',
  pathClassName,
  centerContent,
}: TechnologyOrbitDisplayProps) {
  return (
    <section className='relative flex h-full w-full flex-col items-center justify-center overflow-hidden rounded-lg'>
      {centerContent ? (
        <div className='z-10'>{centerContent}</div>
      ) : (
        <span
          className={cn(
            'pointer-events-none z-10 whitespace-pre-wrap bg-clip-text text-center text-6xl font-semibold leading-none text-transparent',
            textClassName
          )}
        >
          {text}
        </span>
      )}

      {iconsArray.map((icon, index) => (
        <OrbitingCircles
          key={index}
          className={icon.className}
          duration={icon.duration}
          delay={icon.delay}
          radius={icon.radius}
          path={icon.path}
          pathClassName={pathClassName}
          reverse={icon.reverse}
        >
          {icon.component()}
        </OrbitingCircles>
      ))}
    </section>
  );
});

// ==================== AnimatedForm Component ====================

type FieldType = 'text' | 'email' | 'password';

type Field = {
  label: string;
  required?: boolean;
  type: FieldType;
  placeholder?: string;
  autoComplete?: string;
  name?: string;
  defaultValue?: string;
  onChange: (event: ChangeEvent<HTMLInputElement>) => void;
};

type AnimatedFormProps = {
  header: string;
  subHeader?: string;
  fields: Field[];
  submitButton: string;
  submittingButton?: string;
  isSubmitting?: boolean;
  textVariantButton?: string;
  errorField?: string;
  fieldPerRow?: number;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
  googleLogin?: string;
  onGoogleLogin?: () => void;
  /** Replaces the default Google button, in the same place */
  googleButton?: ReactNode;
  goTo?: (event: React.MouseEvent<HTMLButtonElement>) => void;
  footer?: ReactNode;
  /** Rendered inside the form, just above the submit button (e.g. a terms checkbox) */
  beforeSubmit?: ReactNode;
  /** Centre the heading above the form */
  centerHeader?: boolean;
  revealColor?: string;
};

type Errors = {
  [key: string]: string;
};

const AnimatedForm = memo(function AnimatedForm({
  header,
  subHeader,
  fields,
  submitButton,
  submittingButton,
  isSubmitting = false,
  textVariantButton,
  errorField,
  onSubmit,
  googleLogin,
  onGoogleLogin,
  googleButton,
  goTo,
  footer,
  beforeSubmit,
  centerHeader = false,
  revealColor = 'var(--brand-tint)',
}: AnimatedFormProps) {
  const [visible, setVisible] = useState<boolean>(false);
  const [errors, setErrors] = useState<Errors>({});

  const toggleVisibility = () => setVisible(!visible);

  const validateForm = (event: FormEvent<HTMLFormElement>) => {
    const currentErrors: Errors = {};
    const form = event.currentTarget;
    fields.forEach((field) => {
      const input = form.elements.namedItem(field.name || field.label) as HTMLInputElement | null;
      const value = input?.value;

      if (field.required && !value) {
        currentErrors[field.label] = `${field.label} is required`;
      }
      if (field.type === 'email' && value && !/\S+@\S+\.\S+/.test(value)) {
        currentErrors[field.label] = 'Invalid email address';
      }
      if (field.type === 'password' && value && value.length < 6) {
        currentErrors[field.label] = 'Password must be at least 6 characters long';
      }
    });
    return currentErrors;
  };

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const formErrors = validateForm(event);
    setErrors(formErrors);
    if (Object.keys(formErrors).length === 0) {
      onSubmit(event);
    }
  };

  return (
    <section className='mx-auto flex w-96 flex-col gap-4 max-md:w-full'>
      <BoxReveal boxColor={revealColor} duration={0.3} className={cn('mb-2', centerHeader && 'mx-auto')}>
        <h2 className={cn('text-3xl font-bold text-(--color-dark)', centerHeader && 'text-center')}>{header}</h2>
      </BoxReveal>

      {subHeader && (
        <BoxReveal boxColor={revealColor} duration={0.3} className='pb-2'>
          <p className='max-w-sm text-sm text-(--color-text-muted)'>{subHeader}</p>
        </BoxReveal>
      )}

      {(googleButton || (googleLogin && onGoogleLogin)) && (
        <>
          <BoxReveal boxColor={revealColor} duration={0.3} overflow='visible' width='unset'>
            {googleButton || (
              <button
                className='group/btn relative h-11 w-full rounded-md border border-(--color-border-light) bg-white font-medium outline-hidden hover:cursor-pointer'
                type='button'
                onClick={onGoogleLogin}
              >
                <span className='flex h-full w-full items-center justify-center gap-3'>
                  <GoogleIcon />
                  {googleLogin}
                </span>
                <BottomGradient />
              </button>
            )}
          </BoxReveal>

          <BoxReveal boxColor={revealColor} duration={0.3} width='100%'>
            <section className='flex items-center gap-4'>
              <hr className='flex-1 border-0 border-t border-solid border-(--color-border)' />
              <p className='text-sm text-(--color-text-muted)'>or</p>
              <hr className='flex-1 border-0 border-t border-solid border-(--color-border)' />
            </section>
          </BoxReveal>
        </>
      )}

      <form onSubmit={handleSubmit} noValidate>
        <section className='mb-4 grid grid-cols-1 gap-3'>
          {fields.map((field) => {
            const id = field.name || field.label;
            const errorId = `${id}-error`;
            return (
              <section key={field.label} className='flex flex-col gap-2'>
                <BoxReveal boxColor={revealColor} duration={0.3}>
                  <Label htmlFor={id}>
                    {field.label} {field.required && <span className='text-(--color-danger)' aria-hidden='true'>*</span>}
                  </Label>
                </BoxReveal>

                <BoxReveal width='100%' boxColor={revealColor} duration={0.3} className='flex w-full flex-col space-y-2'>
                  <section className='relative'>
                    <Input
                      type={field.type === 'password' ? (visible ? 'text' : 'password') : field.type}
                      id={id}
                      name={id}
                      placeholder={field.placeholder}
                      autoComplete={field.autoComplete}
                      defaultValue={field.defaultValue}
                      aria-invalid={Boolean(errors[field.label])}
                      aria-describedby={errors[field.label] ? errorId : undefined}
                      className={field.type === 'password' ? 'pr-11' : undefined}
                      onChange={field.onChange}
                    />

                    {field.type === 'password' && (
                      <button
                        type='button'
                        onClick={toggleVisibility}
                        aria-label={visible ? 'Hide password' : 'Show password'}
                        aria-pressed={visible}
                        className='absolute inset-y-0 right-0 flex items-center pr-3 text-(--color-text-muted) hover:cursor-pointer hover:text-(--color-dark)'
                      >
                        {visible ? <EyeOff className='h-5 w-5' /> : <Eye className='h-5 w-5' />}
                      </button>
                    )}
                  </section>

                  <section className='min-h-4'>
                    {errors[field.label] && (
                      <p id={errorId} className='pt-1.5 text-xs text-(--color-danger-text)'>{errors[field.label]}</p>
                    )}
                  </section>
                </BoxReveal>
              </section>
            );
          })}
        </section>

        <BoxReveal width='100%' boxColor={revealColor} duration={0.3}>
          {errorField && (
            <p className='mb-4 rounded-md border border-(--color-danger-border) bg-(--color-danger-bg) px-3 py-2 text-sm text-(--color-danger-text)' role='alert'>
              {errorField}
            </p>
          )}
        </BoxReveal>

        {beforeSubmit && (
          <BoxReveal width='100%' boxColor={revealColor} duration={0.3}>
            <div className='mb-4'>{beforeSubmit}</div>
          </BoxReveal>
        )}

        <BoxReveal width='100%' boxColor={revealColor} duration={0.3} overflow='visible'>
          <button
            className='group/btn relative block h-11 w-full rounded-md bg-gradient-to-br from-(--brand-blue) to-(--brand-blue-hover) font-semibold text-white shadow-[0px_1px_0px_0px_#ffffff40_inset,0px_-1px_0px_0px_#ffffff40_inset] outline-hidden hover:cursor-pointer disabled:cursor-not-allowed disabled:opacity-70'
            type='submit'
            disabled={isSubmitting}
          >
            {isSubmitting ? submittingButton || submitButton : <>{submitButton} &rarr;</>}
            <BottomGradient />
          </button>
        </BoxReveal>

        {textVariantButton && goTo && (
          <BoxReveal boxColor={revealColor} duration={0.3} width='100%'>
            <section className='mt-4 text-center'>
              <button
                type='button'
                className='text-sm font-medium text-(--brand-blue) outline-hidden hover:cursor-pointer hover:underline'
                onClick={goTo}
              >
                {textVariantButton}
              </button>
            </section>
          </BoxReveal>
        )}
      </form>

      {footer}
    </section>
  );
});

const BottomGradient = () => {
  return (
    <>
      <span className='absolute inset-x-0 -bottom-px block h-px w-full bg-gradient-to-r from-transparent via-(--brand-cyan) to-transparent opacity-0 transition duration-500 group-hover/btn:opacity-100' />
      <span className='absolute inset-x-10 -bottom-px mx-auto block h-px w-1/2 bg-gradient-to-r from-transparent via-(--brand-sky) to-transparent opacity-0 blur-sm transition duration-500 group-hover/btn:opacity-100' />
    </>
  );
};

// ==================== AuthTabs Component ====================

interface AuthTabsProps {
  formFields: Omit<AnimatedFormProps, 'onSubmit' | 'goTo'>;
  goTo: (event: React.MouseEvent<HTMLButtonElement>) => void;
  handleSubmit: (event: React.FormEvent<HTMLFormElement>) => void;
}

const AuthTabs = memo(function AuthTabs({ formFields, goTo, handleSubmit }: AuthTabsProps) {
  return (
    <div className='flex w-full max-lg:justify-center md:w-auto'>
      <div className='flex h-[100dvh] w-full flex-col items-center justify-center max-lg:px-[10%] lg:w-1/2'>
        <AnimatedForm {...formFields} fieldPerRow={1} onSubmit={handleSubmit} goTo={goTo} />
      </div>
    </div>
  );
});

// ==================== Label Component ====================

interface LabelProps extends React.LabelHTMLAttributes<HTMLLabelElement> {
  htmlFor?: string;
}

const Label = memo(function Label({ className, ...props }: LabelProps) {
  return (
    <label
      className={cn(
        'text-sm font-medium leading-none text-(--color-dark) peer-disabled:cursor-not-allowed peer-disabled:opacity-70',
        className
      )}
      {...props}
    />
  );
});

// ==================== Exports ====================

export {
  Input,
  BoxReveal,
  Ripple,
  OrbitingCircles,
  TechOrbitDisplay,
  AnimatedForm,
  AuthTabs,
  Label,
  BottomGradient,
};
