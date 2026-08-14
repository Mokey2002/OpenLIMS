import { Button } from "react-bootstrap";

export default function AssistantClarification({ clarification, disabled, onChoose }) {
  const options = clarification?.options || [];
  if (!options.length) return null;

  return (
    <div className="assistant-clarification" role="group" aria-label={clarification.question}>
      <div className="assistant-clarification-options">
        {options.map((option) => (
          <Button
            key={option.id || option.message}
            type="button"
            variant="outline-dark"
            className="assistant-clarification-option"
            disabled={disabled}
            onClick={() => onChoose(option.message)}
          >
            <span className="assistant-clarification-option-label">
              {option.label}
            </span>
            {option.description && (
              <span className="assistant-clarification-option-description">
                {option.description}
              </span>
            )}
          </Button>
        ))}
      </div>
    </div>
  );
}
